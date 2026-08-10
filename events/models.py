import hmac
import hashlib
import secrets
from django.db import models
from django.contrib.postgres.fields import ArrayField


def generate_secret():
    return secrets.token_hex(32)


def sign_payload(payload, secret_key):
    return hmac.new(
        secret_key.encode('utf-8'),
        payload.encode('utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()


class Event(models.Model):
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)


class Subscriber(models.Model):
    subscribed_events = ArrayField(models.CharField(max_length=100), blank=True, default=list)
    url = models.URLField(max_length=200)
    secret = models.CharField(max_length=64, default=generate_secret)
    is_active = models.BooleanField(default=True)

class Delivery(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE)
    attempt_count = models.IntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class DeliveryAttempt(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE)
    attempted_at = models.DateTimeField(auto_now_add=True)
    http_result = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
