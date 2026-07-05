"""
Profile models for the Resume AI platform.

Stores structured professional profile data as JSON, validated against
the profile schema defined in /backend/schemas/profile.json.
"""

import uuid
from django.db import models
from django.conf import settings


class Profile(models.Model):
    """
    Stores the user's structured professional profile data.
    
    As per API contract:
    - One profile per user (OneToOne relationship)
    - Data stored as JSON matching the profile schema
    - Contains: personalInfo, summary, experience, education, skills, certifications
    
    The actual validation of the JSON structure happens in the serializer/service layer
    using jsonschema to validate against /backend/schemas/profile.json.
    
    Note: Experience, Education, Certifications are stored within the data JSONField,
    NOT as separate models. This simplifies the schema and reduces joins.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    data = models.JSONField(
        default=dict,
        help_text='Full profile structure as defined in schemas/profile.json'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'profiles'
        indexes = [
            models.Index(fields=['user']),
        ]
    
    def __str__(self):
        full_name = self.data.get('personalInfo', {}).get('full_name', 'Unknown')
        return f"Profile: {full_name} ({self.user.email})"
    
    @property
    def personal_info(self):
        """Convenience accessor for personalInfo section."""
        return self.data.get('personalInfo', {})
    
    @property
    def summary(self):
        """Convenience accessor for summary section."""
        return self.data.get('summary', '')
    
    @property
    def experience(self):
        """Convenience accessor for experience section."""
        return self.data.get('experience', [])
    
    @property
    def education(self):
        """Convenience accessor for education section."""
        return self.data.get('education', [])
    
    @property
    def skills(self):
        """Convenience accessor for skills section."""
        return self.data.get('skills', [])
    
    @property
    def certifications(self):
        """Convenience accessor for certifications section."""
        return self.data.get('certifications', [])


class ProfileSaveEvent(models.Model):
    """
    Records profile section save events for dashboard history.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile_save_events'
    )
    sections = models.JSONField(
        help_text='Top-level profile section keys saved in this event'
    )
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'profile_save_events'
        ordering = ['-saved_at']
        indexes = [
            models.Index(fields=['user', '-saved_at']),
        ]

    def __str__(self):
        return f"ProfileSaveEvent({self.user.email}, {self.sections})"
