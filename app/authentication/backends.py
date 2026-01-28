"""
Custom authentication backends for the Resume AI platform.

Implements JWT bearer token authentication as per API contract.
"""

import jwt
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.backends import ModelBackend
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from app.authentication.models import User

logger = logging.getLogger(__name__)


class EmailBackend(ModelBackend):
    """
    Custom Django authentication backend that authenticates users by email.
    
    This backend allows Django's authenticate() function to work with email
    instead of username, which is required for the custom User model.
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate a user by email and password.
        
        Args:
            request: The request object
            username: The email address (passed as 'username' parameter)
            password: The password
            **kwargs: Additional keyword arguments
        
        Returns:
            User instance if authentication succeeds, None otherwise
        """
        if username is None:
            username = kwargs.get('email')
        
        if username is None or password is None:
            logger.debug("EmailBackend: Missing username or password")
            return None
        
        try:
            # Normalize email to lowercase
            email = username.lower()
            logger.debug(f"EmailBackend: Attempting to authenticate user with email: {email}")
            user = User.objects.get(email=email)
            logger.debug(f"EmailBackend: User found: {user.email}, is_active: {user.is_active}")
        except User.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user
            logger.debug(f"EmailBackend: User not found for email: {email}")
            User().set_password(password)
            return None
        
        # Check password
        password_valid = user.check_password(password)
        can_authenticate = self.user_can_authenticate(user)
        logger.debug(f"EmailBackend: Password valid: {password_valid}, can_authenticate: {can_authenticate}")
        
        if password_valid and can_authenticate:
            logger.info(f"EmailBackend: Authentication successful for user: {user.email}")
            return user
        
        logger.debug(f"EmailBackend: Authentication failed for user: {user.email}")
        return None
    
    def user_can_authenticate(self, user):
        """
        Reject users with is_active=False. Custom user models that don't have
        that attribute are allowed.
        """
        is_active = getattr(user, 'is_active', True)
        return is_active


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    Session authentication that does not require CSRF.
    
    This is used for API endpoints that use session-based authentication
    but need to work with frontend apps that don't send CSRF tokens.
    
    Note: This is safe because we're using CORS to restrict which origins
    can access the API, and cookies have SameSite protection.
    """
    
    def enforce_csrf(self, request):
        """Skip CSRF validation for API requests."""
        return  # Skip CSRF check


class JWTAuthentication(BaseAuthentication):
    """
    JWT Bearer token authentication.
    
    Validates tokens in the Authorization header:
    Authorization: Bearer <token>
    
    Token payload:
    {
        "user_id": "<uuid>",
        "exp": <expiration_timestamp>,
        "iat": <issued_at_timestamp>
    }
    """
    
    keyword = 'Bearer'
    
    def authenticate(self, request):
        """
        Authenticate the request and return a tuple of (user, token) or None.
        """
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return None
        
        parts = auth_header.split()
        
        if parts[0].lower() != self.keyword.lower():
            return None
        
        if len(parts) == 1:
            raise AuthenticationFailed('Invalid Authorization header. No credentials provided.')
        
        if len(parts) > 2:
            raise AuthenticationFailed('Invalid Authorization header. Token should not contain spaces.')
        
        token = parts[1]
        
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=['HS256']
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Token has expired.')
        except jwt.InvalidTokenError:
            raise AuthenticationFailed('Invalid token.')
        
        user_id = payload.get('user_id')
        if not user_id:
            raise AuthenticationFailed('Invalid token payload.')
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise AuthenticationFailed('User not found.')
        
        if not user.is_active:
            raise AuthenticationFailed('User account is disabled.')
        
        return (user, token)
    
    def authenticate_header(self, request):
        """
        Return the WWW-Authenticate header value for 401 responses.
        """
        return self.keyword


def generate_jwt_token(user: User, expiry_hours: int = 24) -> str:
    """
    Generate a JWT token for the given user.
    
    Args:
        user: The user to generate a token for
        expiry_hours: Token validity period in hours
    
    Returns:
        Encoded JWT token string
    """
    now = datetime.utcnow()
    payload = {
        'user_id': str(user.id),
        'iat': now,
        'exp': now + timedelta(hours=expiry_hours),
    }
    
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


def decode_jwt_token(token: str) -> dict:
    """
    Decode and validate a JWT token.
    
    Args:
        token: The JWT token to decode
    
    Returns:
        Decoded token payload
    
    Raises:
        jwt.ExpiredSignatureError: If the token has expired
        jwt.InvalidTokenError: If the token is invalid
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
