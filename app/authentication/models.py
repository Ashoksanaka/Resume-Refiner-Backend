"""
Authentication models for the Resume AI platform.

Implements a custom User model with email-based authentication
as required by the API specification.
"""

import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone


class UserManager(BaseUserManager):
    """
    Custom user manager for email-based authentication.
    """
    
    def create_user(self, email, password=None, **extra_fields):
        """
        Create and return a regular user with an email and password.
        """
        if not email:
            raise ValueError('The Email field must be set')
        
        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_verified', False)
        
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create and return a superuser with an email and password.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_verified', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom User model that uses email for authentication instead of username.
    
    As per API contract:
    - id: UUID (primary key)
    - email: unique email address
    - is_verified: boolean flag for email verification
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    email = models.EmailField(
        unique=True,
        max_length=255,
        error_messages={
            'unique': 'A user with that email already exists.',
        }
    )
    username = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        unique=False  # Not used for auth, but kept for Django admin compatibility
    )
    is_verified = models.BooleanField(
        default=False,
        help_text='Designates whether this user has verified their email address.'
    )
    
    # Override default fields
    first_name = None  # We don't use these; full_name is in Profile
    last_name = None
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # Email and password are required by default
    
    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['is_verified']),
        ]
    
    def __str__(self):
        return self.email
    
    def save(self, *args, **kwargs):
        """
        Auto-generate username from email if not provided.
        """
        if not self.username:
            self.username = self.email.split('@')[0][:150]
        super().save(*args, **kwargs)


class EmailVerificationToken(models.Model):
    """
    Token for email verification during signup.
    
    Tokens expire after EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS (default: 24h).
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='verification_tokens'
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'email_verification_tokens'
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Verification token for {self.user.email}"
    
    @property
    def is_valid(self):
        """
        Check if the token is still valid (not expired and not used).
        """
        return (
            self.used_at is None and
            self.expires_at > timezone.now()
        )
    
    def mark_used(self):
        """
        Mark the token as used.
        """
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])


class PasswordResetToken(models.Model):
    """
    Token for password reset functionality.
    
    Tokens expire after 1 hour for security.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_reset_tokens'
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'password_reset_tokens'
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Password reset token for {self.user.email}"
    
    @property
    def is_valid(self):
        """Check if the token is still valid (not expired and not used)."""
        return (
            self.used_at is None and
            self.expires_at > timezone.now()
        )
    
    def mark_used(self):
        """Mark the token as used."""
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])


class IdempotencyKey(models.Model):
    """
    Tracks idempotency keys for preventing duplicate operations.
    
    Used primarily for resume generation to prevent duplicate requests.
    Keys expire after 24 hours.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='idempotency_keys'
    )
    key = models.CharField(max_length=64, db_index=True)
    endpoint = models.CharField(max_length=255)
    response_status = models.IntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = 'idempotency_keys'
        unique_together = ['user', 'key', 'endpoint']
        indexes = [
            models.Index(fields=['key']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Idempotency key {self.key} for {self.user.email}"
    
    @property
    def is_valid(self):
        """
        Check if the idempotency key is still valid (not expired).
        """
        return self.expires_at > timezone.now()
