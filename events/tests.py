import json
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import Membership, Organization
from events.models import Delivery, DeliveryAttempt, Event, Subscriber, sign_payload
from events.services import fan_out_event
from events.tasks import deliver_webhook, retry_failed_deliveries


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Acme")


@pytest.fixture
def auth_client(client, db, organization):
    user = User.objects.create_user(username="tester", password="pass")
    token = Token.objects.create(user=user)
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.ADMIN)
    client.defaults["HTTP_AUTHORIZATION"] = f"Token {token.key}"
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(organization.id)
    return client


def test_sign_payload_is_deterministic():
    signature_1 = sign_payload("{'a': 1}", "secret")
    signature_2 = sign_payload("{'a': 1}", "secret")
    assert signature_1 == signature_2


def test_sign_payload_changes_with_secret():
    signature_1 = sign_payload("{'a': 1}", "secret-a")
    signature_2 = sign_payload("{'a': 1}", "secret-b")
    assert signature_1 != signature_2


def test_sign_payload_changes_with_payload():
    signature_1 = sign_payload("{'a': 1}", "secret")
    signature_2 = sign_payload("{'a': 2}", "secret")
    assert signature_1 != signature_2


@pytest.mark.django_db
def test_create_event_returns_201(auth_client, organization):
    response = auth_client.post(
        "/events/",
        data=json.dumps({"event_type": "order.paid", "payload": {"order_id": 1}}),
        content_type="application/json",
    )
    assert response.status_code == 201
    assert Event.objects.count() == 1
    assert Event.objects.get().organization == organization


@pytest.mark.django_db
def test_create_event_without_event_type_returns_400(auth_client):
    response = auth_client.post(
        "/events/",
        data=json.dumps({"payload": {"order_id": 1}}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert Event.objects.count() == 0


@pytest.mark.django_db
def test_create_subscriber_returns_secret(auth_client, organization):
    response = auth_client.post(
        "/events/subscribers/",
        data=json.dumps({"url": "https://example.com", "subscribed_events": ["order.paid"]}),
        content_type="application/json",
    )
    assert response.status_code == 201
    assert "secret" in response.json()
    assert response.json()["is_active"] is True
    assert Subscriber.objects.get().organization == organization


@pytest.mark.django_db
def test_create_event_without_token_returns_401(client):
    response = client.post(
        "/events/",
        data=json.dumps({"event_type": "order.paid", "payload": {"order_id": 1}}),
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_create_event_without_organization_header_returns_403():
    user = User.objects.create_user(username="tester", password="pass")
    token = Token.objects.create(user=user)
    organization = Organization.objects.create(name="Acme")
    Membership.objects.create(user=user, organization=organization)

    client = Client()
    response = client.post(
        "/events/",
        data=json.dumps({"event_type": "order.paid", "payload": {"order_id": 1}}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Token {token.key}",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_fan_out_creates_delivery_for_matching_active_subscriber(organization):
    subscriber = Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.paid"],
        organization=organization,
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1}, organization=organization)

    fan_out_event(event)

    assert Delivery.objects.filter(event=event, subscriber=subscriber).exists()


@pytest.mark.django_db
def test_fan_out_skips_inactive_subscriber(organization):
    Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.paid"],
        is_active=False,
        organization=organization,
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1}, organization=organization)

    fan_out_event(event)

    assert Delivery.objects.filter(event=event).count() == 0


@pytest.mark.django_db
def test_fan_out_skips_non_matching_event_type(organization):
    Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.refunded"],
        organization=organization,
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1}, organization=organization)

    fan_out_event(event)

    assert Delivery.objects.filter(event=event).count() == 0


@pytest.mark.django_db
def test_fan_out_only_delivers_within_same_organization():
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    subscriber_a = Subscriber.objects.create(
        url="https://a.example.com", subscribed_events=["order.paid"], organization=org_a,
    )
    subscriber_b = Subscriber.objects.create(
        url="https://b.example.com", subscribed_events=["order.paid"], organization=org_b,
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1}, organization=org_a)

    fan_out_event(event)

    assert Delivery.objects.filter(event=event, subscriber=subscriber_a).exists()
    assert not Delivery.objects.filter(event=event, subscriber=subscriber_b).exists()


def _make_delivery(organization, **kwargs):
    subscriber = Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.paid"],
        organization=organization,
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1}, organization=organization)
    defaults = {
        "event": event,
        "subscriber": subscriber,
        "next_attempt_at": timezone.now(),
    }
    defaults.update(kwargs)
    return Delivery.objects.create(**defaults)


@pytest.mark.django_db
def test_deliver_webhook_marks_success_on_2xx(organization):
    delivery = _make_delivery(organization)

    fake_response = Mock(status_code=200)
    with patch("events.tasks.requests.post", return_value=fake_response):
        deliver_webhook(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.SUCCESS
    assert delivery.attempt_count == 1
    attempt = DeliveryAttempt.objects.get(delivery=delivery)
    assert attempt.http_result == 200
    assert attempt.error_message is None


@pytest.mark.django_db
def test_deliver_webhook_sends_matching_signature_and_body(organization):
    delivery = _make_delivery(organization)

    fake_response = Mock(status_code=200)
    with patch("events.tasks.requests.post", return_value=fake_response) as mock_post:
        deliver_webhook(delivery.id)

    _, kwargs = mock_post.call_args
    expected_signature = sign_payload(kwargs["data"], delivery.subscriber.secret)
    assert kwargs["headers"]["X-Signature"] == expected_signature
    assert json.loads(kwargs["data"]) == delivery.event.payload


@pytest.mark.django_db
def test_deliver_webhook_schedules_retry_on_connection_error(organization):
    delivery = _make_delivery(organization)

    with patch("events.tasks.requests.post", side_effect=requests.exceptions.ConnectionError("boom")):
        deliver_webhook(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.PENDING
    assert delivery.attempt_count == 1
    assert delivery.next_attempt_at > timezone.now()
    attempt = DeliveryAttempt.objects.get(delivery=delivery)
    assert attempt.error_message == "boom"
    assert attempt.http_result is None


@pytest.mark.django_db
def test_deliver_webhook_schedules_retry_on_error_status_code(organization):
    delivery = _make_delivery(organization)

    fake_response = Mock(status_code=500)
    with patch("events.tasks.requests.post", return_value=fake_response):
        deliver_webhook(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.PENDING
    attempt = DeliveryAttempt.objects.get(delivery=delivery)
    assert attempt.http_result == 500


@pytest.mark.django_db
def test_deliver_webhook_marks_failed_after_max_attempts(organization):
    delivery = _make_delivery(organization, attempt_count=settings.MAX_DELIVERY_ATTEMPTS - 1)

    with patch("events.tasks.requests.post", side_effect=requests.exceptions.ConnectionError("boom")):
        deliver_webhook(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.FAILED
    assert delivery.attempt_count == settings.MAX_DELIVERY_ATTEMPTS


@pytest.mark.django_db
def test_retry_failed_deliveries_enqueues_due_pending_deliveries(organization):
    due_delivery = _make_delivery(
        organization,
        status=Delivery.Status.PENDING,
        attempt_count=1,
        next_attempt_at=timezone.now() - timedelta(seconds=1),
    )

    with patch("events.tasks.deliver_webhook.delay") as mock_delay:
        retry_failed_deliveries()

    mock_delay.assert_called_once_with(delivery_id=due_delivery.id)


@pytest.mark.django_db
def test_retry_failed_deliveries_skips_brand_new_delivery(organization):
    _make_delivery(
        organization,
        status=Delivery.Status.PENDING,
        attempt_count=0,
        next_attempt_at=timezone.now() - timedelta(seconds=1),
    )

    with patch("events.tasks.deliver_webhook.delay") as mock_delay:
        retry_failed_deliveries()

    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_retry_failed_deliveries_skips_not_yet_due(organization):
    _make_delivery(
        organization,
        status=Delivery.Status.PENDING,
        attempt_count=1,
        next_attempt_at=timezone.now() + timedelta(minutes=5),
    )

    with patch("events.tasks.deliver_webhook.delay") as mock_delay:
        retry_failed_deliveries()

    mock_delay.assert_not_called()
