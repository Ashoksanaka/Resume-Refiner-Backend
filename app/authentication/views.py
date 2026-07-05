"""
Authentication API views for the Resume AI platform.

Clerk handles sign-in/sign-up on the frontend. The backend exposes:
- GET /auth/me
- POST /auth/clerk/webhook
"""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from svix.webhooks import Webhook, WebhookVerificationError

from app.authentication.clerk_services import ClerkUserSyncService
from app.authentication.serializers import UserSerializer

logger = logging.getLogger(__name__)


class MeView(APIView):
    """GET /auth/me - return the authenticated local user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ClerkWebhookView(APIView):
    """POST /auth/clerk/webhook - sync Clerk user lifecycle events."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        secret = getattr(settings, 'CLERK_WEBHOOK_SECRET', '')
        if not secret:
            logger.error('CLERK_WEBHOOK_SECRET is not configured')
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        headers = {
            'svix-id': request.headers.get('svix-id', ''),
            'svix-timestamp': request.headers.get('svix-timestamp', ''),
            'svix-signature': request.headers.get('svix-signature', ''),
        }

        try:
            payload = Webhook(secret).verify(request.body, headers)
        except WebhookVerificationError:
            logger.warning('Invalid Clerk webhook signature')
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event_type = payload.get('type')
        data = payload.get('data', {})

        try:
            if event_type == 'user.created':
                ClerkUserSyncService.upsert_from_clerk_event(data)
            elif event_type == 'user.updated':
                ClerkUserSyncService.upsert_from_clerk_event(data)
            elif event_type == 'user.deleted':
                ClerkUserSyncService.deactivate_from_clerk_event(data)
        except ValueError as exc:
            logger.warning('Clerk webhook processing failed: %s', exc)
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception('Unexpected Clerk webhook error for event %s', event_type)
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'received': True}, status=status.HTTP_200_OK)
