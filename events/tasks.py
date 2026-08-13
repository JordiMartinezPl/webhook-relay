import json

import requests
from celery import shared_task
from django.conf import settings

from .models import Delivery, DeliveryAttempt, sign_payload


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
        else:
            delivery.status = Delivery.Status.FAILED
        DeliveryAttempt.objects.create(
            delivery=delivery,
            http_result=response.status_code,
        )
    except requests.RequestException as e:
        delivery.attempt_count += 1
        delivery.status = Delivery.Status.FAILED
        DeliveryAttempt.objects.create(
            delivery=delivery,
            error_message=str(e),
        )
    finally:
        delivery.save()
