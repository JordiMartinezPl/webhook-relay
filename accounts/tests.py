import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import Invitation, Membership, Organization


@pytest.mark.django_db
def test_register_creates_organization_user_and_membership(client):
    response = client.post(
        "/accounts/register/",
        data=json.dumps({
            "organization_name": "Acme Inc",
            "username": "jordi",
            "email": "jordi@example.com",
            "password": "supersecret123",
        }),
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert "token" in body
    assert body["username"] == "jordi"

    user = User.objects.get(username="jordi")
    organization = Organization.objects.get(id=body["organization_id"])
    assert Membership.objects.filter(user=user, organization=organization, role=Membership.Role.ADMIN).exists()
    assert Token.objects.get(user=user).key == body["token"]


@pytest.mark.django_db
def test_register_token_can_be_used_on_protected_endpoints(client):
    response = client.post(
        "/accounts/register/",
        data=json.dumps({
            "organization_name": "Acme Inc",
            "username": "jordi",
            "email": "jordi@example.com",
            "password": "supersecret123",
        }),
        content_type="application/json",
    )
    body = response.json()

    event_response = client.post(
        "/events/",
        data=json.dumps({"event_type": "order.paid", "payload": {"order_id": 1}}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {body['token']}",
        HTTP_X_ORGANIZATION_ID=str(body["organization_id"]),
    )

    assert event_response.status_code == 201


@pytest.mark.django_db
def test_register_without_username_returns_400(client):
    response = client.post(
        "/accounts/register/",
        data=json.dumps({"organization_name": "Acme Inc", "password": "supersecret123"}),
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_create_invitation_by_admin_succeeds(client):
    register_response = client.post(
        "/accounts/register/",
        data=json.dumps({
            "organization_name": "Acme Inc",
            "username": "jordi",
            "email": "jordi@example.com",
            "password": "supersecret123",
        }),
        content_type="application/json",
    )
    body = register_response.json()

    response = client.post(
        "/accounts/invitations/",
        data=json.dumps({"email": "newmember@example.com", "role": Membership.Role.MEMBER}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {body['token']}",
        HTTP_X_ORGANIZATION_ID=str(body["organization_id"]),
    )

    assert response.status_code == 201
    admin = User.objects.get(username="jordi")
    invitation = Invitation.objects.get(email="newmember@example.com")
    assert invitation.organization_id == body["organization_id"]
    assert invitation.invited_by == admin


@pytest.mark.django_db
def test_create_invitation_by_non_admin_returns_403(client):
    register_response = client.post(
        "/accounts/register/",
        data=json.dumps({
            "organization_name": "Acme Inc",
            "username": "jordi",
            "email": "jordi@example.com",
            "password": "supersecret123",
        }),
        content_type="application/json",
    )
    body = register_response.json()
    organization = Organization.objects.get(id=body["organization_id"])

    member = User.objects.create_user(username="member", password="supersecret123")
    Membership.objects.create(user=member, organization=organization, role=Membership.Role.MEMBER)
    member_token = Token.objects.create(user=member)

    response = client.post(
        "/accounts/invitations/",
        data=json.dumps({"email": "newmember@example.com", "role": Membership.Role.MEMBER}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {member_token.key}",
        HTTP_X_ORGANIZATION_ID=str(body["organization_id"]),
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_accept_invitation_creates_membership(client):
    organization = Organization.objects.create(name="Acme Inc")
    invitation = Invitation.objects.create(
        email="newmember@example.com",
        organization=organization,
        role=Membership.Role.MEMBER,
    )
    invitee = User.objects.create_user(username="invitee", password="supersecret123", email="newmember@example.com")
    invitee_token = Token.objects.create(user=invitee)

    response = client.post(
        f"/accounts/invitations/{invitation.token}/accept/",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {invitee_token.key}",
    )

    assert response.status_code == 200
    assert Membership.objects.filter(user=invitee, organization=organization, role=Membership.Role.MEMBER).exists()
    invitation.refresh_from_db()
    assert invitation.accepted_at is not None


@pytest.mark.django_db
def test_accept_invitation_twice_returns_400(client):
    organization = Organization.objects.create(name="Acme Inc")
    invitation = Invitation.objects.create(
        email="newmember@example.com",
        organization=organization,
        accepted_at=timezone.now(),
    )
    invitee = User.objects.create_user(username="invitee", password="supersecret123", email="newmember@example.com")
    invitee_token = Token.objects.create(user=invitee)

    response = client.post(
        f"/accounts/invitations/{invitation.token}/accept/",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {invitee_token.key}",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_accept_invitation_with_mismatched_email_returns_403(client):
    organization = Organization.objects.create(name="Acme Inc")
    invitation = Invitation.objects.create(
        email="newmember@example.com",
        organization=organization,
    )
    other_user = User.objects.create_user(username="stranger", password="supersecret123", email="stranger@example.com")
    other_token = Token.objects.create(user=other_user)

    response = client.post(
        f"/accounts/invitations/{invitation.token}/accept/",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {other_token.key}",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_accept_expired_invitation_returns_400(client):
    organization = Organization.objects.create(name="Acme Inc")
    invitation = Invitation.objects.create(
        email="newmember@example.com",
        organization=organization,
        expiration_date=timezone.now() - timedelta(days=1),
    )
    invitee = User.objects.create_user(username="invitee", password="supersecret123", email="newmember@example.com")
    invitee_token = Token.objects.create(user=invitee)

    response = client.post(
        f"/accounts/invitations/{invitation.token}/accept/",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {invitee_token.key}",
    )

    assert response.status_code == 400
