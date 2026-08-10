from django.urls import path
from . import views

urlpatterns = [
    path('', views.create_event, name='create-event'),
    path('subscribers/', views.create_subscriber, name='create_subscriber'),
]