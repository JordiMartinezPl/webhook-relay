from rest_framework.permissions import BasePermission

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