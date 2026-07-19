"""
Authentication Celery tasks for the Resume AI platform.

Handles periodic maintenance tasks:
- Cleanup of expired idempotency keys
"""

import logging

from celery import shared_task
from django.utils import timezone

from app.authentication.models import IdempotencyKey

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_idempotency_keys():
    """Delete all expired idempotency keys."""
    now = timezone.now()

    count = IdempotencyKey.objects.filter(expires_at__lte=now).count()

    if count > 0:
        IdempotencyKey.objects.filter(expires_at__lte=now).delete()
        logger.info("Deleted %d expired idempotency keys", count)

    return {'idempotency_keys_deleted': count}
