"""
Authentication services for the Resume AI platform.

Business logic for:
- User registration and email verification
- Token generation and validation
- Session management
"""

import secrets
import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from app.authentication.models import User, EmailVerificationToken, PasswordResetToken
from app.authentication.backends import generate_jwt_token
from app.common.exceptions import InvalidTokenException, EmailNotVerifiedException
from app.common.email import email_service

logger = logging.getLogger(__name__)

# Password reset token expiry (1 hour for security)
PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 1


class AuthenticationService:
    """
    Service class for authentication-related business logic.
    """
    
    @staticmethod
    def create_user(email: str, password: str) -> User:
        """
        Create a new user account.
        
        Args:
            email: User's email address
            password: User's password
        
        Returns:
            Created User instance
        
        Note: The user is NOT verified at this point.
        """
        email = email.lower()
        user = User.objects.create_user(email=email, password=password)
        logger.info("User created: %s", user.id)  # Log ID only, not email (PII)
        return user
    
    @staticmethod
    def generate_verification_token(user: User) -> str:
        """
        Generate an email verification token for a user.
        
        Args:
            user: The user to generate a token for
        
        Returns:
            The generated token string
        """
        # Invalidate any existing tokens
        EmailVerificationToken.objects.filter(user=user, used_at__isnull=True).delete()
        
        # Generate new token
        token = secrets.token_urlsafe(32)
        expiry_hours = getattr(settings, 'EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS', 24)
        
        EmailVerificationToken.objects.create(
            user=user,
            token=token,
            expires_at=timezone.now() + timedelta(hours=expiry_hours)
        )
        
        logger.info("Verification token generated for user: %s", user.id)
        return token
    
    @staticmethod
    def send_verification_email(user: User, token: str) -> bool:
        """
        Send verification email to user using SendGrid.
        
        Args:
            user: The user to send the email to
            token: The verification token
        
        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            success = email_service.send_verification_email(
                to_email=user.email,
                token=token,
                user_name=None  # We don't have the name until profile is created
            )
            
            if success:
                logger.info("Verification email sent to user: %s", user.id)
            else:
                logger.error("Failed to send verification email for user: %s", user.id)
            
            return success
            
        except Exception as e:
            logger.exception("Error sending verification email for user %s: %s", user.id, type(e).__name__)
            # Don't raise - user is still created, they can request a new token
            return False
    
    @staticmethod
    def verify_email(token: str) -> User:
        """
        Verify a user's email using the verification token.
        
        Args:
            token: The verification token
        
        Returns:
            The verified User instance
        
        Raises:
            InvalidTokenException: If the token is invalid or expired
        """
        try:
            verification_token = EmailVerificationToken.objects.get(token=token)
        except EmailVerificationToken.DoesNotExist:
            raise InvalidTokenException('Invalid verification token.')
        
        if not verification_token.is_valid:
            raise InvalidTokenException('Verification token has expired.')
        
        # Mark token as used
        verification_token.mark_used()
        
        # Mark user as verified
        user = verification_token.user
        user.is_verified = True
        user.save(update_fields=['is_verified'])
        
        logger.info("User email verified: %s", user.id)
        return user
    
    @staticmethod
    def login_user(user: User) -> dict:
        """
        Log in a user and generate tokens.
        
        Args:
            user: The authenticated user
        
        Returns:
            Dict with user data and tokens
        """
        # Generate JWT token
        access_token = generate_jwt_token(user)
        
        logger.info("User logged in: %s", user.id)
        
        return {
            'user': user,
            'access_token': access_token,
        }
    
    @staticmethod
    def require_verified_email(user: User) -> None:
        """
        Check that a user has verified their email.
        
        Args:
            user: The user to check
        
        Raises:
            EmailNotVerifiedException: If email is not verified
        """
        if not user.is_verified:
            raise EmailNotVerifiedException()
    
    @staticmethod
    def generate_password_reset_token(user: User) -> str:
        """
        Generate a password reset token for a user.
        
        Args:
            user: The user to generate a token for
        
        Returns:
            The generated token string
        """
        # Invalidate any existing tokens
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).delete()
        
        # Generate new token
        token = secrets.token_urlsafe(32)
        
        PasswordResetToken.objects.create(
            user=user,
            token=token,
            expires_at=timezone.now() + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRY_HOURS)
        )
        
        logger.info("Password reset token generated for user: %s", user.id)
        return token
    
    @staticmethod
    def send_password_reset_email(user: User, token: str) -> bool:
        """
        Send password reset email to user.
        
        Args:
            user: The user to send the email to
            token: The reset token
        
        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            success = email_service.send_password_reset_email(
                to_email=user.email,
                token=token,
                user_name=None
            )
            
            if success:
                logger.info("Password reset email sent to user: %s", user.id)
            else:
                logger.error("Failed to send password reset email for user: %s", user.id)
            
            return success
            
        except Exception as e:
            logger.exception("Error sending password reset email for user %s: %s", user.id, type(e).__name__)
            return False
    
    @staticmethod
    def reset_password(token: str, new_password: str) -> User:
        """
        Reset a user's password using the reset token.
        
        Args:
            token: The password reset token
            new_password: The new password
        
        Returns:
            The User instance
        
        Raises:
            InvalidTokenException: If the token is invalid or expired
        """
        try:
            reset_token = PasswordResetToken.objects.get(token=token)
        except PasswordResetToken.DoesNotExist:
            raise InvalidTokenException('Invalid password reset token.')
        
        if not reset_token.is_valid:
            raise InvalidTokenException('Password reset token has expired.')
        
        # Mark token as used
        reset_token.mark_used()
        
        # Update password
        user = reset_token.user
        user.set_password(new_password)
        user.save(update_fields=['password'])
        
        logger.info("Password reset for user: %s", user.id)
        return user
