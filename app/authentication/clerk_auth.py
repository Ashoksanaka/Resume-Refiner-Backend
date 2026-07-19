"""
Clerk JWT authentication for the Resume AI platform.

Verifies Clerk session JWTs via JWKS and resolves local User records.
"""

import logging
import time
from typing import Any, Optional

import jwt
import httpx
from django.conf import settings
from django.db import transaction
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from app.authentication.models import User

logger = logging.getLogger(__name__)

_jwks_cache: dict[str, Any] = {'keys': None, 'fetched_at': 0.0}


def _get_clerk_audience() -> str:
    return getattr(settings, 'CLERK_AUDIENCE', '') or ''


def _fetch_clerk_user_email(clerk_id: str) -> Optional[str]:
    """Fetch primary email from Clerk Backend API when JWT claims omit it."""
    secret = getattr(settings, 'CLERK_SECRET_KEY', '')
    if not secret:
        return None

    from app.authentication.clerk_services import _extract_primary_email

    try:
        api_base = (
            getattr(settings, 'CLERK_API_BASE_URL', '') or ''
        ).rstrip('/')
        if not api_base:
            logger.error('CLERK_API_BASE_URL is not configured')
            return None

        response = httpx.get(
            f'{api_base}/users/{clerk_id}',
            headers={'Authorization': f'Bearer {secret}'},
            timeout=10.0,
        )
        response.raise_for_status()
        return _extract_primary_email(response.json())
    except httpx.HTTPError as exc:
        logger.error('Failed to fetch Clerk user %s: %s', clerk_id, type(exc).__name__)
        return None


def _fetch_jwks() -> dict[str, Any]:
    """Fetch and cache Clerk JWKS."""
    ttl = getattr(settings, 'CLERK_JWKS_CACHE_TTL', 3600)
    now = time.time()

    if _jwks_cache['keys'] is not None and (now - _jwks_cache['fetched_at']) < ttl:
        return _jwks_cache['keys']

    issuer = getattr(settings, 'CLERK_JWT_ISSUER', '').rstrip('/')
    if not issuer:
        raise AuthenticationFailed('Clerk JWT issuer is not configured.')

    url = f'{issuer}/.well-known/jwks.json'
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        jwks = response.json()
    except httpx.HTTPError as exc:
        logger.error('Failed to fetch Clerk JWKS: %s', type(exc).__name__)
        if _jwks_cache['keys'] is not None:
            return _jwks_cache['keys']
        raise AuthenticationFailed('Unable to verify authentication token.') from exc

    _jwks_cache['keys'] = jwks
    _jwks_cache['fetched_at'] = now
    return jwks


def _get_signing_key_from_jwks(jwks: dict[str, Any], token: str):
    """Resolve the RSA signing key for a JWT from cached JWKS."""
    jwk_set = jwt.PyJWKSet.from_dict(jwks)
    header = jwt.get_unverified_header(token)
    kid = header.get('kid')
    if not kid:
        raise AuthenticationFailed('Invalid token.')
    try:
        return jwk_set[kid].key
    except KeyError as exc:
        raise AuthenticationFailed('Invalid token.') from exc


def _extract_email(payload: dict[str, Any]) -> Optional[str]:
    """Extract primary email from Clerk JWT claims."""
    if payload.get('email'):
        return str(payload['email']).lower()

    email_addresses = payload.get('email_addresses')
    if isinstance(email_addresses, list) and email_addresses:
        first = email_addresses[0]
        if isinstance(first, dict) and first.get('email_address'):
            return str(first['email_address']).lower()
        if isinstance(first, str):
            return first.lower()

    return None


def _get_or_create_user_from_claims(clerk_id: str, payload: dict[str, Any]) -> User:
    """Resolve local user by clerk_id, with JIT provisioning fallback."""
    user = User.objects.filter(clerk_id=clerk_id).first()
    if user:
        if not user.is_active:
            raise AuthenticationFailed('User account is disabled.')
        return user

    email = _extract_email(payload)
    if not email:
        email = _fetch_clerk_user_email(clerk_id)
    if not email:
        raise AuthenticationFailed('Unable to resolve user from token.')

    with transaction.atomic():
        user = User.objects.filter(email=email).first()
        if user:
            if user.clerk_id and user.clerk_id != clerk_id:
                raise AuthenticationFailed('User account mismatch.')
            user.clerk_id = clerk_id
            user.is_verified = True
            user.save(update_fields=['clerk_id', 'is_verified'])
            return user

        user = User.objects.create(
            email=email,
            clerk_id=clerk_id,
            is_verified=True,
            is_active=True,
        )
        user.set_unusable_password()
        user.save(update_fields=['password'])
        logger.info('JIT provisioned user from Clerk JWT: %s', user.id)
        return user


def verify_clerk_token(token: str) -> tuple[User, dict[str, Any]]:
    """Verify a Clerk session JWT and return the local user and payload."""
    issuer = getattr(settings, 'CLERK_JWT_ISSUER', '').rstrip('/')
    audience = _get_clerk_audience()

    if not issuer:
        raise AuthenticationFailed('Clerk JWT issuer is not configured.')

    try:
        jwks = _fetch_jwks()
        signing_key = _get_signing_key_from_jwks(jwks, token)
        decode_kwargs: dict[str, Any] = {
            'algorithms': ['RS256'],
            'issuer': issuer,
            'options': {'require': ['exp', 'sub']},
        }
        if audience:
            decode_kwargs['audience'] = audience
        payload = jwt.decode(token, signing_key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationFailed('Token has expired.') from exc
    except jwt.InvalidTokenError as exc:
        logger.warning('Clerk JWT decode failed: %s', str(exc)[:200])
        raise AuthenticationFailed('Invalid token.') from exc

    clerk_id = payload.get('sub')
    if not clerk_id:
        raise AuthenticationFailed('Invalid token payload.')

    user = _get_or_create_user_from_claims(clerk_id, payload)
    return user, payload


class ClerkJWTAuthentication(BaseAuthentication):
    """
    Authenticate API requests using Clerk session JWTs.

    Authorization: Bearer <clerk_session_jwt>
    """

    keyword = 'Bearer'

    def authenticate(self, request):
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
        user, _payload = verify_clerk_token(token)
        return (user, token)

    def authenticate_header(self, request):
        return self.keyword
