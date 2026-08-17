from rest_framework import serializers

from events import models
from .models import Event, Membership, Organization, Subscriber , Delivery

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'created_at']
        read_only_fields = ['created_at']

class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ['id', 'user', 'organization', 'role', 'joined_at']
        read_only_fields = ['joined_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'organization'], name='unique_membership_per_org')
            ]