from rest_framework.permissions import BasePermission

from .models import Membership


class HasOrganizationPermission(BasePermission):

    def has_permission(self, request, view):
        organization_id = request.META.get('HTTP_X_ORGANIZATION_ID')
        if not organization_id:
            return False
        membership = request.user.membership_set.filter(organization_id=organization_id).first()
        if not membership:
            return False
        request.organization = membership.organization
        return True


class IsOrganizationAdmin(BasePermission):

    def has_permission(self, request, view):
        membership = Membership.objects.filter(
            user=request.user,
            organization=request.organization,
        ).first()
        return membership is not None and membership.role == Membership.Role.ADMIN