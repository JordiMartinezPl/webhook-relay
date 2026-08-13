import json
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
import requests
from django.conf import settings
from django.utils import timezone

from events.models import Delivery, DeliveryAttempt, Event, Subscriber, sign_payload
from events.services import fan_out_event
from events.tasks import deliver_webhook, retry_failed_deliveries


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
def test_create_event_returns_201(client):
    response = client.post(
        "/events/",
        data=json.dumps({"event_type": "order.paid", "payload": {"order_id": 1}}),
        content_type="application/json",
    )
    assert response.status_code == 201
    assert Event.objects.count() == 1


@pytest.mark.django_db
def test_create_event_without_event_type_returns_400(client):
    response = client.post(
        "/events/",
        data=json.dumps({"payload": {"order_id": 1}}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert Event.objects.count() == 0


@pytest.mark.django_db
def test_create_subscriber_returns_secret(client):
    response = client.post(
        "/events/subscribers/",
        data=json.dumps({"url": "https://example.com", "subscribed_events": ["order.paid"]}),
        content_type="application/json",
    )
    assert response.status_code == 201
    assert "secret" in response.json()
    assert response.json()["is_active"] is True


@pytest.mark.django_db
def test_fan_out_creates_delivery_for_matching_active_subscriber():
    subscriber = Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.paid"],
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1})

    fan_out_event(event)

    assert Delivery.objects.filter(event=event, subscriber=subscriber).exists()


@pytest.mark.django_db
def test_fan_out_skips_inactive_subscriber():
    Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.paid"],
        is_active=False,
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1})

    fan_out_event(event)

    assert Delivery.objects.filter(event=event).count() == 0


@pytest.mark.django_db
def test_fan_out_skips_non_matching_event_type():
    Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.refunded"],
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1})

    fan_out_event(event)

    assert Delivery.objects.filter(event=event).count() == 0


def _make_delivery(**kwargs):
    subscriber = Subscriber.objects.create(
        url="https://example.com",
        subscribed_events=["order.paid"],
    )
    event = Event.objects.create(event_type="order.paid", payload={"order_id": 1})
    defaults = {
        "event": event,
        "subscriber": subscriber,
        "next_attempt_at": timezone.now(),
    }
    defaults.update(kwargs)
    return Delivery.objects.create(**defaults)


@pytest.mark.django_db
def test_deliver_webhook_marks_success_on_2xx():
    delivery = _make_delivery()

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
def test_deliver_webhook_sends_matching_signature_and_body():
    delivery = _make_delivery()

    fake_response = Mock(status_code=200)
    with patch("events.tasks.requests.post", return_value=fake_response) as mock_post:
        deliver_webhook(delivery.id)

    _, kwargs = mock_post.call_args
    expected_signature = sign_payload(kwargs["data"], delivery.subscriber.secret)
    assert kwargs["headers"]["X-Signature"] == expected_signature
    assert json.loads(kwargs["data"]) == delivery.event.payload


@pytest.mark.django_db
def test_deliver_webhook_schedules_retry_on_connection_error():
    delivery = _make_delivery()

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
def test_deliver_webhook_schedules_retry_on_error_status_code():
    delivery = _make_delivery()

    fake_response = Mock(status_code=500)
    with patch("events.tasks.requests.post", return_value=fake_response):
        deliver_webhook(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.PENDING
    attempt = DeliveryAttempt.objects.get(delivery=delivery)
    assert attempt.http_result == 500


@pytest.mark.django_db
def test_deliver_webhook_marks_failed_after_max_attempts():
    delivery = _make_delivery(attempt_count=settings.MAX_DELIVERY_ATTEMPTS - 1)

    with patch("events.tasks.requests.post", side_effect=requests.exceptions.ConnectionError("boom")):
        deliver_webhook(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.FAILED
    assert delivery.attempt_count == settings.MAX_DELIVERY_ATTEMPTS


@pytest.mark.django_db
def test_retry_failed_deliveries_enqueues_due_pending_deliveries():
    due_delivery = _make_delivery(
        status=Delivery.Status.PENDING,
        attempt_count=1,
        next_attempt_at=timezone.now() - timedelta(seconds=1),
    )

    with patch("events.tasks.deliver_webhook.delay") as mock_delay:
        retry_failed_deliveries()

    mock_delay.assert_called_once_with(delivery_id=due_delivery.id)


@pytest.mark.django_db
def test_retry_failed_deliveries_skips_brand_new_delivery():
    _make_delivery(
        status=Delivery.Status.PENDING,
        attempt_count=0,
        next_attempt_at=timezone.now() - timedelta(seconds=1),
    )

    with patch("events.tasks.deliver_webhook.delay") as mock_delay:
        retry_failed_deliveries()

    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_retry_failed_deliveries_skips_not_yet_due():
    _make_delivery(
        status=Delivery.Status.PENDING,
        attempt_count=1,
        next_attempt_at=timezone.now() + timedelta(minutes=5),
    )

    with patch("events.tasks.deliver_webhook.delay") as mock_delay:
        retry_failed_deliveries()

    mock_delay.assert_not_called()
