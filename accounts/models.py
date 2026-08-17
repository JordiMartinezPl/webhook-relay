import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone


def generate_secret():
    return secrets.token_hex(32)


def default_expiration():
    return timezone.now() + timedelta(days=7)


class Organization(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

class Membership(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        MEMBER = 'member', 'Member'
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    role = models.CharField(max_length=50, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'organization'], name='unique_membership_per_org')
        ]

class Invitation(models.Model):
    email = models.EmailField()
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    role = models.CharField(max_length=50, choices=Membership.Role.choices, default=Membership.Role.MEMBER)
    expiration_date = models.DateTimeField(default=default_expiration)
    invited_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    token = models.CharField(max_length=64, unique=True, default=generate_secret)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['email', 'organization'], name='unique_invitation_per_org')
        ]
