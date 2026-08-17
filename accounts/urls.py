from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('invitations/', views.create_invitation, name='create-invitation'),
    path('invitations/<str:token>/accept/', views.accept_invitation, name='accept-invitation'),
]