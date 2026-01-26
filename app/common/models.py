"""
Common models for the Resume AI platform.

Contains abstract base classes and shared model utilities.
"""

import uuid
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone


class TimeStampedModel(models.Model):
    """
    Abstract base class for models with created_at and updated_at timestamps.
    """
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True


class TemporaryResource(TimeStampedModel):
    """
    Abstract base class for models that should be automatically purged after a TTL.
    
    As per requirements:
    - All temporary resources (job descriptions, resume generation requests) expire after 24 hours
    - A background job/cron will periodically delete expired records
    - Attempting to GET an expired resource returns HTTP 410 Gone
    
    Usage:
        TemporaryResource.objects.filter(expires_at__lte=timezone.now()).delete()
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    expires_at = models.DateTimeField(db_index=True)
    
    class Meta:
        abstract = True
    
    def save(self, *args, **kwargs):
        """
        Automatically set expires_at if not provided.
        """
        if not self.expires_at:
            ttl_hours = getattr(settings, 'DATA_TTL_HOURS', 24)
            self.expires_at = timezone.now() + timedelta(hours=ttl_hours)
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        """
        Check if the resource has expired.
        """
        return timezone.now() >= self.expires_at
    
    @classmethod
    def delete_expired(cls):
        """
        Delete all expired resources of this type.
        Returns the count of deleted objects.
        """
        result = cls.objects.filter(expires_at__lte=timezone.now()).delete()
        return result[0] if result else 0


class Template(models.Model):
    """
    Resume template metadata.
    
    Templates are managed by the LaTeX microservice and synced to this database.
    The LaTeX service is the source of truth for templates.
    """
    
    id = models.CharField(
        primary_key=True,
        max_length=100,
        help_text='Slug-style identifier, e.g., "altacv"'
    )
    name = models.CharField(
        max_length=255,
        help_text='Human-readable template name'
    )
    description = models.TextField(
        blank=True,
        help_text='Description of the template style and use case'
    )
    author = models.CharField(
        max_length=255,
        blank=True,
        help_text='Template author'
    )
    version = models.CharField(
        max_length=20,
        default='1.0.0',
        help_text='Semantic version (X.Y.Z) for cache invalidation'
    )
    default_filename = models.CharField(
        max_length=100,
        default='resume',
        help_text='Default filename for generated PDFs'
    )
    has_preview = models.BooleanField(
        default=False,
        help_text='Whether preview images are available'
    )
    preview_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the preview was last generated'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Whether the template is available for selection'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'templates'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} (v{self.version})"
    
    @property
    def preview_png_url(self) -> str:
        """URL for PNG preview (served by backend, proxied from LaTeX service)."""
        return f"/api/v1/templates/{self.id}/preview.png"
    
    @property
    def preview_pdf_url(self) -> str:
        """URL for PDF preview (served by backend, proxied from LaTeX service)."""
        return f"/api/v1/templates/{self.id}/preview.pdf"
