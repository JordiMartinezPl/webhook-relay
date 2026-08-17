from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from rest_framework.permissions import IsAuthenticated
from accounts.permissions import HasOrganizationPermission
from .serializers import EventSerializer, SubscriberSerializer
from . import services

@api_view(['POST'])
@permission_classes([IsAuthenticated, HasOrganizationPermission])
def create_event(request):
    serializer = EventSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(organization=request.organization)
        services.fan_out_event(serializer.instance)
        return Response(serializer.data,status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated, HasOrganizationPermission])
def create_subscriber(request):
    serializer = SubscriberSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(organization=request.organization)
        return Response(serializer.data,status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status.HTTP_400_BAD_REQUEST)

