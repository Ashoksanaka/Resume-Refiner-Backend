"""
Clerk user sync services for the Resume AI platform.
"""

import logging
from typing import Any, Optional

from django.db import transaction

from app.authentication.models import User

logger = logging.getLogger(__name__)


def _extract_primary_email(data: dict[str, Any]) -> Optional[str]:
    email_addresses = data.get('email_addresses') or []
    primary_id = data.get('primary_email_address_id')

    for entry in email_addresses:
        if not isinstance(entry, dict):
            continue
        if primary_id and entry.get('id') == primary_id:
            email = entry.get('email_address')
            if email:
                return email.lower()

    for entry in email_addresses:
        if isinstance(entry, dict) and entry.get('email_address'):
            return str(entry['email_address']).lower()

    return None


class ClerkUserSyncService:
    """Sync Clerk webhook events to local User records."""

    @staticmethod
    def upsert_from_clerk_event(data: dict[str, Any]) -> User:
        clerk_id = data.get('id')
        if not clerk_id:
            raise ValueError('Clerk user id is required.')

        email = _extract_primary_email(data)
        if not email:
            raise ValueError('Clerk user email is required.')

        with transaction.atomic():
            user = User.objects.filter(clerk_id=clerk_id).first()
            if user:
                user.email = email
                user.is_verified = True
                user.is_active = True
                user.save(update_fields=['email', 'is_verified', 'is_active'])
                return user

            user = User.objects.filter(email=email).first()
            if user:
                user.clerk_id = clerk_id
                user.is_verified = True
                user.is_active = True
                user.save(update_fields=['clerk_id', 'is_verified', 'is_active'])
                return user

            user = User.objects.create(
                email=email,
                clerk_id=clerk_id,
                is_verified=True,
                is_active=True,
            )
            user.set_unusable_password()
            user.save(update_fields=['password'])
            logger.info('Created user from Clerk webhook: %s', user.id)
            return user

    @staticmethod
    def deactivate_from_clerk_event(data: dict[str, Any]) -> None:
        clerk_id = data.get('id')
        if not clerk_id:
            return

        updated = User.objects.filter(clerk_id=clerk_id).update(is_active=False)
        if updated:
            logger.info('Deactivated user from Clerk webhook: %s', clerk_id)
