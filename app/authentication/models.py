"""
Authentication models for the Resume AI platform.

Implements a custom User model with email-based authentication
as required by the API specification.
"""

import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.auth.password_validation import validate_password
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
        if password is not None:
            validate_password(password, user)
            user.set_password(password)
        else:
            user.set_unusable_password()
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
    clerk_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text='Clerk user ID (sub claim from session JWT).'
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
            models.Index(fields=['clerk_id']),
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
