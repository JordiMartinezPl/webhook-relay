import json
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Delivery, DeliveryAttempt, sign_payload

RETRY_SCHEDULE = [5, 30, 60]


def _schedule_retry_or_fail(delivery, http_result=None, error_message=None):
    if delivery.attempt_count >= settings.MAX_DELIVERY_ATTEMPTS:
        delivery.status = Delivery.Status.FAILED
    else:
        delivery.status = Delivery.Status.PENDING
        delay = RETRY_SCHEDULE[min(delivery.attempt_count - 1, len(RETRY_SCHEDULE) - 1)]
        delivery.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    DeliveryAttempt.objects.create(
        delivery=delivery,
        http_result=http_result,
        error_message=error_message,
    )


@shared_task
def deliver_webhook(delivery_id):
    delivery = Delivery.objects.get(id=delivery_id)
    event = delivery.event
    subscriber = delivery.subscriber

    payload_str = json.dumps(event.payload)
    signature = sign_payload(payload_str, subscriber.secret)

    try:
        response = requests.post(
            subscriber.url,
            data=payload_str,
            headers={
                'Content-Type': 'application/json',
                'X-Signature': signature,
            },
            timeout=settings.WEBHOOK_TIMEOUT,
        )
        delivery.attempt_count += 1
        if 200 <= response.status_code < 300:
            delivery.status = Delivery.Status.SUCCESS
            DeliveryAttempt.objects.create(
                delivery=delivery,
                http_result=response.status_code,
            )
        else:
            _schedule_retry_or_fail(delivery, http_result=response.status_code)
    except requests.RequestException as e:
        delivery.attempt_count += 1
        _schedule_retry_or_fail(delivery, error_message=str(e))
    finally:
        delivery.save()


@shared_task
def retry_failed_deliveries():
    pending_deliveries = Delivery.objects.filter(
        status=Delivery.Status.PENDING,
        attempt_count__gt=0,
        next_attempt_at__lte=timezone.now(),
    )
    for delivery in pending_deliveries:
        deliver_webhook.delay(delivery_id=delivery.id)
