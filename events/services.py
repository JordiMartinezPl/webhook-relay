from django.utils import timezone
from .models import Subscriber, Delivery
from .tasks import deliver_webhook

def fan_out_event(event):
    subscribers = Subscriber.objects.filter(is_active=True, subscribed_events__contains=[event.event_type])
    for subscriber in subscribers:
        delivery = Delivery.objects.create(
            event=event,
            subscriber=subscriber,
            next_attempt_at=timezone.now(),
        )
        deliver_webhook.delay(delivery_id=delivery.id)