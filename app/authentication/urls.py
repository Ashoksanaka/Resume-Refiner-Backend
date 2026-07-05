"""
URL patterns for authentication endpoints.
"""

from django.urls import path

from app.authentication.views import ClerkWebhookView, MeView

app_name = 'authentication'

urlpatterns = [
    path('me', MeView.as_view(), name='me'),
    path('clerk/webhook', ClerkWebhookView.as_view(), name='clerk-webhook'),
]
