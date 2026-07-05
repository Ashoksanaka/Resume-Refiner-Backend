"""
Integration tests for authentication endpoints.

Tests:
- Clerk JWT authentication
- GET /auth/me
- Clerk webhook user sync
"""

import json
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from app.authentication.clerk_auth import verify_clerk_token
from app.authentication.models import User


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def verified_user(db):
    user = User.objects.create_user(
        email='test@example.com',
        password='testpass123',
    )
    user.clerk_id = 'user_clerk_test123'
    user.is_verified = True
    user.save()
    return user


@pytest.fixture
def clerk_settings():
    with override_settings(
        CLERK_JWT_ISSUER='https://clerk.example.com',
        CLERK_AUDIENCE='',
        CLERK_WEBHOOK_SECRET='whsec_test_secret',
    ):
        yield


@pytest.mark.django_db
class TestMe:
    """Tests for GET /auth/me"""

    def test_me_success(self, api_client, verified_user):
        api_client.force_authenticate(user=verified_user)

        response = api_client.get('/api/v1/auth/me')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == str(verified_user.id)
        assert response.data['email'] == verified_user.email
        assert response.data['is_verified'] is True

    def test_me_unauthenticated(self, api_client):
        response = api_client.get('/api/v1/auth/me')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestClerkJWTAuthentication:
    """Tests for Clerk JWT verification and JIT provisioning."""

    @patch('app.authentication.clerk_auth._fetch_jwks')
    @patch('app.authentication.clerk_auth._get_signing_key_from_jwks')
    def test_verify_clerk_token_existing_user(
        self,
        mock_get_signing_key,
        mock_fetch_jwks,
        verified_user,
        clerk_settings,
    ):
        mock_fetch_jwks.return_value = {'keys': []}
        mock_get_signing_key.return_value = 'test-key'

        payload = {
            'sub': verified_user.clerk_id,
            'email': verified_user.email,
            'exp': 9999999999,
        }

        with patch('jwt.decode', return_value=payload):
            user, _ = verify_clerk_token('fake-token')

        assert user.id == verified_user.id

    @patch('app.authentication.clerk_auth._fetch_jwks')
    @patch('app.authentication.clerk_auth._get_signing_key_from_jwks')
    def test_verify_clerk_token_jit_provision(
        self,
        mock_get_signing_key,
        mock_fetch_jwks,
        clerk_settings,
    ):
        mock_fetch_jwks.return_value = {'keys': []}
        mock_get_signing_key.return_value = 'test-key'

        payload = {
            'sub': 'user_clerk_new456',
            'email': 'newuser@example.com',
            'exp': 9999999999,
        }

        with patch('jwt.decode', return_value=payload):
            user, _ = verify_clerk_token('fake-token')

        assert user.clerk_id == 'user_clerk_new456'
        assert user.email == 'newuser@example.com'
        assert user.is_verified is True


@pytest.mark.django_db
class TestClerkWebhook:
    """Tests for POST /auth/clerk/webhook"""

    @patch('app.authentication.views.Webhook')
    def test_user_created_webhook(self, mock_webhook_class, api_client, clerk_settings):
        mock_webhook_class.return_value.verify.return_value = {
            'type': 'user.created',
            'data': {
                'id': 'user_clerk_webhook1',
                'primary_email_address_id': 'idn_1',
                'email_addresses': [
                    {'id': 'idn_1', 'email_address': 'webhook@example.com'},
                ],
            },
        }

        response = api_client.post(
            '/api/v1/auth/clerk/webhook',
            data=json.dumps({'type': 'user.created'}),
            content_type='application/json',
            HTTP_SVIX_ID='msg_1',
            HTTP_SVIX_TIMESTAMP='1234567890',
            HTTP_SVIX_SIGNATURE='v1,signature',
        )

        assert response.status_code == status.HTTP_200_OK
        user = User.objects.get(clerk_id='user_clerk_webhook1')
        assert user.email == 'webhook@example.com'
        assert user.is_verified is True

    @patch('app.authentication.views.Webhook')
    def test_invalid_webhook_signature(self, mock_webhook_class, api_client, clerk_settings):
        from svix.webhooks import WebhookVerificationError

        mock_webhook_class.return_value.verify.side_effect = WebhookVerificationError('invalid')

        response = api_client.post(
            '/api/v1/auth/clerk/webhook',
            data=json.dumps({'type': 'user.created'}),
            content_type='application/json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch('app.authentication.views.Webhook')
    def test_user_deleted_webhook(self, mock_webhook_class, api_client, verified_user, clerk_settings):
        mock_webhook_class.return_value.verify.return_value = {
            'type': 'user.deleted',
            'data': {'id': verified_user.clerk_id},
        }

        response = api_client.post(
            '/api/v1/auth/clerk/webhook',
            data=json.dumps({'type': 'user.deleted'}),
            content_type='application/json',
        )

        assert response.status_code == status.HTTP_200_OK
        verified_user.refresh_from_db()
        assert verified_user.is_active is False
