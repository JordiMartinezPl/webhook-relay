from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from .models import Membership, Organization


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


class RegisterSerializer(serializers.Serializer):
    organization_name = serializers.CharField()
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def create(self, validated_data):
        organization = Organization.objects.create(name=validated_data['organization_name'])
        user = User.objects.create_user(username=validated_data['username'], password=validated_data['password'])
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.ADMIN)
        token = Token.objects.create(user=user)
        return {
            'token': token.key,
            'organization_id': organization.id,
            'username': user.username,
        }
