"""
Authentication Celery tasks for the Resume AI platform.

Handles periodic maintenance tasks:
- Cleanup of expired verification tokens
- Cleanup of expired idempotency keys
- Cleanup of expired password reset tokens
"""

import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from app.authentication.models import EmailVerificationToken, IdempotencyKey, PasswordResetToken

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_tokens():
    """
    Delete all expired email verification and password reset tokens.
    
    This task runs daily via Celery Beat.
    """
    now = timezone.now()
    
    # Delete expired verification tokens
    verify_count = EmailVerificationToken.objects.filter(expires_at__lte=now).count()
    
    if verify_count > 0:
        EmailVerificationToken.objects.filter(expires_at__lte=now).delete()
        logger.info("Deleted %d expired verification tokens", verify_count)
    
    # Also delete used verification tokens older than 7 days
    used_count = EmailVerificationToken.objects.filter(
        used_at__isnull=False,
        used_at__lt=now - timedelta(days=7)
    ).count()
    
    if used_count > 0:
        EmailVerificationToken.objects.filter(
            used_at__isnull=False,
            used_at__lt=now - timedelta(days=7)
        ).delete()
        logger.info("Deleted %d old used verification tokens", used_count)
    
    # Delete expired password reset tokens
    reset_count = PasswordResetToken.objects.filter(expires_at__lte=now).count()
    
    if reset_count > 0:
        PasswordResetToken.objects.filter(expires_at__lte=now).delete()
        logger.info("Deleted %d expired password reset tokens", reset_count)
    
    # Delete used password reset tokens older than 1 day
    used_reset_count = PasswordResetToken.objects.filter(
        used_at__isnull=False,
        used_at__lt=now - timedelta(days=1)
    ).count()
    
    if used_reset_count > 0:
        PasswordResetToken.objects.filter(
            used_at__isnull=False,
            used_at__lt=now - timedelta(days=1)
        ).delete()
        logger.info("Deleted %d old used password reset tokens", used_reset_count)
    
    return {
        'expired_verification_tokens_deleted': verify_count,
        'old_used_verification_tokens_deleted': used_count,
        'expired_reset_tokens_deleted': reset_count,
        'old_used_reset_tokens_deleted': used_reset_count,
    }


@shared_task
def cleanup_expired_idempotency_keys():
    """
    Delete all expired idempotency keys.
    
    This task runs daily via Celery Beat.
    """
    now = timezone.now()
    
    count = IdempotencyKey.objects.filter(expires_at__lte=now).count()
    
    if count > 0:
        IdempotencyKey.objects.filter(expires_at__lte=now).delete()
        logger.info("Deleted %d expired idempotency keys", count)
    
    return {'idempotency_keys_deleted': count}


@shared_task
def send_verification_email_async(user_id: str, token: str):
    """
    Send verification email asynchronously.
    
    This offloads email sending to a background task for better API response times.
    """
    from app.authentication.models import User
    from app.authentication.services import AuthenticationService
    
    try:
        user = User.objects.get(id=user_id)
        AuthenticationService.send_verification_email(user, token)
    except User.DoesNotExist:
        logger.error("User not found for verification email: %s", user_id)
    except Exception as e:
        logger.error("Failed to send verification email for user %s: %s", user_id, str(e))
