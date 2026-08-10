from rest_framework import serializers
from .models import Event, Subscriber

class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ['id', 'event_type', 'payload', 'received_at']
        read_only_fields = ['received_at']

class SubscriberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscriber
        fields = ['id','subscribed_events','url','is_active','secret']
        read_only_fields = ['secret']
