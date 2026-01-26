"""
Integration tests for authentication endpoints.

Tests:
- User signup and email verification flow
- Login/logout
- Auth required endpoints
- Password policy and strength endpoints
"""

import pytest
from unittest.mock import patch
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from app.authentication.models import User, EmailVerificationToken
from app.authentication.services import AuthenticationService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def verified_user(db):
    """Create a verified user for testing."""
    user = User.objects.create_user(
        email='test@example.com',
        password='testpass123'
    )
    user.is_verified = True
    user.save()
    return user


@pytest.fixture
def unverified_user(db):
    """Create an unverified user for testing."""
    return User.objects.create_user(
        email='unverified@example.com',
        password='testpass123'
    )


@pytest.mark.django_db
class TestSignup:
    """Tests for POST /auth/signup"""
    
    def test_signup_success(self, api_client):
        """Test successful user registration."""
        response = api_client.post(
            '/api/v1/auth/signup',
            {
                'email': 'newuser@example.com',
                'password': 'SecurePass123!',
                'confirm_password': 'SecurePass123!'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['message'] == 'Verification email sent'
        assert User.objects.filter(email='newuser@example.com').exists()
        
        user = User.objects.get(email='newuser@example.com')
        assert not user.is_verified
    
    def test_signup_creates_verification_token(self, api_client):
        """Test that signup creates a verification token."""
        api_client.post(
            '/api/v1/auth/signup',
            {
                'email': 'tokentest@example.com',
                'password': 'SecurePass123!',
                'confirm_password': 'SecurePass123!'
            },
            format='json'
        )
        
        user = User.objects.get(email='tokentest@example.com')
        assert EmailVerificationToken.objects.filter(user=user).exists()
    
    def test_signup_duplicate_email(self, api_client, verified_user):
        """Test signup with existing email returns 409."""
        response = api_client.post(
            '/api/v1/auth/signup',
            {
                'email': verified_user.email,
                'password': 'SecurePass123!',
                'confirm_password': 'SecurePass123!'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'EMAIL_ALREADY_REGISTERED'
        assert 'message' in response.data
    
    def test_signup_invalid_email(self, api_client):
        """Test signup with invalid email format returns structured errors."""
        response = api_client.post(
            '/api/v1/auth/signup',
            {
                'email': 'notanemail',
                'password': 'SecurePass123!',
                'confirm_password': 'SecurePass123!'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'INVALID_PAYLOAD'
        assert 'errors' in response.data
        assert any(e['field'] == 'email' and e['code'] == 'INVALID_EMAIL_FORMAT' 
                   for e in response.data['errors'])
    
    def test_signup_weak_password(self, api_client):
        """Test signup with weak password returns structured errors."""
        response = api_client.post(
            '/api/v1/auth/signup',
            {
                'email': 'weakpass@example.com',
                'password': '123',
                'confirm_password': '123'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'INVALID_PAYLOAD'
        assert 'errors' in response.data
        assert any(e['field'] == 'password' and e['code'] == 'PASSWORD_TOO_WEAK'
                   for e in response.data['errors'])
    
    def test_signup_password_mismatch(self, api_client):
        """Test signup with mismatched passwords returns structured errors."""
        response = api_client.post(
            '/api/v1/auth/signup',
            {
                'email': 'mismatch@example.com',
                'password': 'SecurePass123!',
                'confirm_password': 'DifferentPass123!'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'INVALID_PAYLOAD'
        assert 'errors' in response.data
        assert any(e['field'] == 'confirm_password' and e['code'] == 'PASSWORD_MISMATCH'
                   for e in response.data['errors'])


@pytest.mark.django_db
class TestVerifyEmail:
    """Tests for POST /auth/verify"""
    
    def test_verify_success(self, api_client, unverified_user):
        """Test successful email verification."""
        token = AuthenticationService.generate_verification_token(unverified_user)
        
        response = api_client.post(
            '/api/v1/auth/verify',
            {'token': token},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        
        unverified_user.refresh_from_db()
        assert unverified_user.is_verified
    
    def test_verify_invalid_token(self, api_client):
        """Test verification with invalid token fails."""
        response = api_client.post(
            '/api/v1/auth/verify',
            {'token': 'invalid-token-xyz'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_TOKEN'
    
    def test_verify_expired_token(self, api_client, unverified_user):
        """Test verification with expired token fails."""
        token = AuthenticationService.generate_verification_token(unverified_user)
        
        # Expire the token
        verification_token = EmailVerificationToken.objects.get(token=token)
        verification_token.expires_at = timezone.now() - timedelta(hours=1)
        verification_token.save()
        
        response = api_client.post(
            '/api/v1/auth/verify',
            {'token': token},
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_TOKEN'


@pytest.mark.django_db
class TestLogin:
    """Tests for POST /auth/login"""
    
    def test_login_success(self, api_client, verified_user):
        """Test successful login."""
        response = api_client.post(
            '/api/v1/auth/login',
            {'email': verified_user.email, 'password': 'testpass123'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'id' in response.data
        assert response.data['email'] == verified_user.email
        assert 'access_token' in response.data
    
    def test_login_invalid_credentials(self, api_client, verified_user):
        """Test login with wrong password returns generic error."""
        response = api_client.post(
            '/api/v1/auth/login',
            {'email': verified_user.email, 'password': 'wrongpassword'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['code'] == 'INVALID_CREDENTIALS'
        assert 'Invalid email or password' in response.data['message']
    
    def test_login_nonexistent_user(self, api_client):
        """Test login with non-existent email returns generic error."""
        response = api_client.post(
            '/api/v1/auth/login',
            {'email': 'nonexistent@example.com', 'password': 'somepassword'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['code'] == 'INVALID_CREDENTIALS'
    
    @patch('app.authentication.views.config')
    def test_login_unverified_email_detailed(self, mock_config, api_client, unverified_user):
        """Test login with unverified email returns detailed error when flag enabled."""
        def config_side_effect(key, default=False, cast=bool):
            if key == 'AUTH_DETAILED_ERRORS':
                return True
            return default
        mock_config.side_effect = config_side_effect
        
        response = api_client.post(
            '/api/v1/auth/login',
            {'email': unverified_user.email, 'password': 'testpass123'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['code'] == 'EMAIL_NOT_VERIFIED'
    
    @patch('app.authentication.views.config')
    def test_login_invalid_password_detailed(self, mock_config, api_client, verified_user):
        """Test login with wrong password returns detailed error when flag enabled."""
        def config_side_effect(key, default=False, cast=bool):
            if key == 'AUTH_DETAILED_ERRORS':
                return True
            return default
        mock_config.side_effect = config_side_effect
        
        response = api_client.post(
            '/api/v1/auth/login',
            {'email': verified_user.email, 'password': 'wrongpassword'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['code'] == 'INVALID_PASSWORD'
    
    @patch('app.authentication.views.config')
    def test_login_locked_account_detailed(self, mock_config, api_client):
        """Test login with locked account returns detailed error when flag enabled."""
        def config_side_effect(key, default=False, cast=bool):
            if key == 'AUTH_DETAILED_ERRORS':
                return True
            return default
        mock_config.side_effect = config_side_effect
        
        locked_user = User.objects.create_user(
            email='locked@example.com',
            password='SecurePass123!'
        )
        locked_user.is_active = False
        locked_user.is_verified = True
        locked_user.save()
        
        response = api_client.post(
            '/api/v1/auth/login',
            {'email': locked_user.email, 'password': 'SecurePass123!'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['code'] == 'ACCOUNT_LOCKED'


@pytest.mark.django_db
class TestLogout:
    """Tests for POST /auth/logout"""
    
    def test_logout_success(self, api_client, verified_user):
        """Test successful logout."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.post('/api/v1/auth/logout')
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
    
    def test_logout_unauthenticated(self, api_client):
        """Test logout without authentication fails."""
        response = api_client.post('/api/v1/auth/logout')
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestMe:
    """Tests for GET /auth/me"""
    
    def test_me_success(self, api_client, verified_user):
        """Test getting current user info."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.get('/api/v1/auth/me')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == str(verified_user.id)
        assert response.data['email'] == verified_user.email
        assert response.data['is_verified'] is True
    
    def test_me_unauthenticated(self, api_client):
        """Test /me without authentication fails."""
        response = api_client.get('/api/v1/auth/me')
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestPasswordPolicy:
    """Tests for GET /auth/password-policy"""
    
    def test_password_policy_success(self, api_client):
        """Test getting password policy."""
        response = api_client.get('/api/v1/auth/password-policy')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['min_length'] == 10
        assert response.data['require_uppercase'] is True
        assert response.data['require_number'] is True
        assert response.data['require_symbol'] is True


@pytest.mark.django_db
class TestPasswordStrength:
    """Tests for POST /auth/password-strength"""
    
    def test_password_strength_valid(self, api_client):
        """Test password strength check with valid password."""
        response = api_client.post(
            '/api/v1/auth/password-strength',
            {'password': 'SecurePass123!'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['valid'] is True
        assert 0 <= response.data['score'] <= 100
    
    def test_password_strength_weak(self, api_client):
        """Test password strength check with weak password."""
        response = api_client.post(
            '/api/v1/auth/password-strength',
            {'password': 'weak'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['valid'] is False
        assert 0 <= response.data['score'] <= 100
    
    def test_password_strength_missing_field(self, api_client):
        """Test password strength check with missing password field."""
        response = api_client.post(
            '/api/v1/auth/password-strength',
            {},
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
