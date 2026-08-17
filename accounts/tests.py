import json

import pytest
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

from accounts.models import Membership, Organization


@pytest.mark.django_db
def test_register_creates_organization_user_and_membership(client):
    response = client.post(
        "/accounts/register/",
        data=json.dumps({
            "organization_name": "Acme Inc",
            "username": "jordi",
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
