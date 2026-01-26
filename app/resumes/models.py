"""
Resume models for the Resume AI platform.

Contains JobDescription and ResumeGenerationRequest models that handle
the resume generation workflow with 24-hour TTL enforcement.
"""

import uuid
from django.db import models
from django.conf import settings
from app.common.models import TemporaryResource


class JobDescription(TemporaryResource):
    """
    Stores an ingested job description text.
    
    As per API contract:
    - Temporary resource that expires after 24 hours (TTL)
    - Raw text storage with 20000 character limit
    - Read-only fields: id, created_at, expires_at
    
    Privacy Note: Raw job description text should NOT be logged.
    Only log the JD id for debugging.
    """
    
    text = models.TextField(
        max_length=20000,
        help_text='Raw text of the job description'
    )
    
    class Meta:
        db_table = 'job_descriptions'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['expires_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"JD {self.id} (user: {self.user_id})"


class ResumeGenerationRequest(TemporaryResource):
    """
    Tracks the state of a resume generation task.
    
    As per API contract:
    - Temporary resource that expires after 24 hours (TTL)
    - Status: pending -> processing -> success/failed
    - Stores generated LaTeX and PDF path on success
    - Stores failure_reason on failure
    
    Status Transitions:
    - pending: Request accepted, waiting to be processed
    - processing: AI agent is generating the resume
    - success: Resume generated and PDF compiled successfully
    - failed: Generation or compilation failed
    
    Failure Codes (failure_reason_code):
    - MODEL_OUTPUT_INVALID: AI produced hallucinated or invalid content
    - LATEX_COMPILE_ERROR: LaTeX failed to compile to PDF
    - AI_SERVICE_ERROR: AI agent service error
    - LATEX_SERVICE_ERROR: LaTeX microservice error
    - TIMEOUT: Generation exceeded time limit
    """
    
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]
    
    # Foreign keys
    job_description = models.ForeignKey(
        JobDescription,
        on_delete=models.CASCADE,
        related_name='resume_requests'
    )
    template_id = models.CharField(
        max_length=100,
        help_text='ID of the selected template'
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True
    )
    
    # Result storage
    generated_latex = models.TextField(
        blank=True,
        null=True,
        help_text='AI-generated LaTeX source code'
    )
    generated_pdf_path = models.CharField(
        max_length=1024,
        blank=True,
        null=True,
        help_text='Path to the compiled PDF file'
    )
    modifications = models.JSONField(
        default=list,
        blank=True,
        help_text='List of human-readable modification summaries made by AI'
    )
    
    # Snapshot of profile at generation time (for reproducibility and hallucination detection)
    profile_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text='Copy of profile data used for generation'
    )
    
    # Error tracking
    failure_reason_code = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        help_text='Machine-readable error code'
    )
    failure_details = models.TextField(
        blank=True,
        null=True,
        help_text='Human-readable error details'
    )
    
    # Idempotency
    idempotency_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text='Client-provided idempotency key to prevent duplicate requests'
    )
    
    # Timing
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When processing started'
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When processing completed (success or failure)'
    )
    
    class Meta:
        db_table = 'resume_generation_requests'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['status']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['idempotency_key']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Resume {self.id} [{self.status}] (user: {self.user_id})"
    
    @property
    def is_complete(self):
        """Check if the generation has completed (success or failure)."""
        return self.status in (self.STATUS_SUCCESS, self.STATUS_FAILED)
    
    @property
    def failure_reason(self):
        """
        Returns the failure reason for API response.
        Combines code and details into a user-friendly message.
        """
        if not self.failure_reason_code:
            return None
        return self.failure_details or self.failure_reason_code
    
    def mark_processing(self):
        """Mark the request as processing."""
        from django.utils import timezone
        self.status = self.STATUS_PROCESSING
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at', 'updated_at'])
    
    def mark_success(self, latex_source: str, pdf_path: str, modifications: list = None):
        """Mark the request as successfully completed."""
        from django.utils import timezone
        self.status = self.STATUS_SUCCESS
        self.generated_latex = latex_source
        self.generated_pdf_path = pdf_path
        self.modifications = modifications or []
        self.completed_at = timezone.now()
        self.save(update_fields=[
            'status', 'generated_latex', 'generated_pdf_path',
            'modifications', 'completed_at', 'updated_at'
        ])
    
    def mark_failed(self, error_code: str, error_details: str = None):
        """Mark the request as failed."""
        from django.utils import timezone
        self.status = self.STATUS_FAILED
        self.failure_reason_code = error_code
        self.failure_details = error_details
        self.completed_at = timezone.now()
        self.save(update_fields=[
            'status', 'failure_reason_code', 'failure_details',
            'completed_at', 'updated_at'
        ])
