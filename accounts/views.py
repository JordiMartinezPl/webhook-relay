from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Invitation, Membership
from .permissions import HasOrganizationPermission, IsOrganizationAdmin
from .serializers import InvitationSerializer, MembershipSerializer, RegisterSerializer


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated, HasOrganizationPermission, IsOrganizationAdmin])
def create_invitation(request):
    serializer = InvitationSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(organization=request.organization, invited_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_invitation(request, token):
    invitation = get_object_or_404(Invitation, token=token)

    if invitation.email != request.user.email:
        return Response({'detail': 'This invitation was sent to a different email address.'}, status=status.HTTP_403_FORBIDDEN)
    if invitation.accepted_at is not None:
        return Response({'detail': 'Invitation already accepted.'}, status=status.HTTP_400_BAD_REQUEST)
    if invitation.expiration_date < timezone.now():
        return Response({'detail': 'Invitation has expired.'}, status=status.HTTP_400_BAD_REQUEST)
    if Membership.objects.filter(user=request.user, organization=invitation.organization).exists():
        return Response({'detail': 'Already a member of this organization.'}, status=status.HTTP_400_BAD_REQUEST)

    membership = Membership.objects.create(
        user=request.user,
        organization=invitation.organization,
        role=invitation.role,
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=['accepted_at'])

    return Response(MembershipSerializer(membership).data, status=status.HTTP_200_OK)
