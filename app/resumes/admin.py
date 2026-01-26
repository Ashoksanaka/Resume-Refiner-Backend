"""
Django admin configuration for resume models.
"""

from django.contrib import admin
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.common.models import Template


@admin.register(JobDescription)
class JobDescriptionAdmin(admin.ModelAdmin):
    """Admin configuration for JobDescription model."""
    
    list_display = ('id', 'user', 'text_preview', 'created_at', 'expires_at', 'is_expired_flag')
    list_filter = ('created_at',)
    search_fields = ('user__email', 'id')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'expires_at')
    
    def text_preview(self, obj):
        """Show first 50 characters of the job description."""
        return f"{obj.text[:50]}..." if len(obj.text) > 50 else obj.text
    text_preview.short_description = 'Text'
    
    def is_expired_flag(self, obj):
        return obj.is_expired
    is_expired_flag.boolean = True
    is_expired_flag.short_description = 'Expired'


@admin.register(ResumeGenerationRequest)
class ResumeGenerationRequestAdmin(admin.ModelAdmin):
    """Admin configuration for ResumeGenerationRequest model."""
    
    list_display = (
        'id', 'user', 'status', 'template_id',
        'created_at', 'completed_at', 'is_expired_flag'
    )
    list_filter = ('status', 'template_id', 'created_at')
    search_fields = ('user__email', 'id', 'idempotency_key')
    ordering = ('-created_at',)
    readonly_fields = (
        'id', 'created_at', 'expires_at', 'started_at', 'completed_at',
        'profile_snapshot', 'generated_latex', 'modifications'
    )
    
    def is_expired_flag(self, obj):
        return obj.is_expired
    is_expired_flag.boolean = True
    is_expired_flag.short_description = 'Expired'
    
    fieldsets = (
        ('Request Info', {
            'fields': ('id', 'user', 'job_description', 'template_id', 'idempotency_key')
        }),
        ('Status', {
            'fields': ('status', 'failure_reason_code', 'failure_details')
        }),
        ('Generated Content', {
            'fields': ('generated_latex', 'generated_pdf_path', 'modifications'),
            'classes': ('collapse',),
        }),
        ('Profile Snapshot', {
            'fields': ('profile_snapshot',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'expires_at', 'started_at', 'completed_at')
        }),
    )


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    """Admin configuration for Template model.
    
    Note: Templates are managed internally and not exposed to users.
    This admin is for internal management only.
    """
    
    list_display = ('id', 'name', 'author', 'version', 'is_active', 'has_preview', 'created_at', 'updated_at')
    list_filter = ('is_active', 'has_preview')
    search_fields = ('id', 'name', 'author')
    ordering = ('name',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'preview_generated_at')
    
    fieldsets = (
        ('Basic Info', {'fields': ('id', 'name', 'description', 'author', 'version')}),
        ('Template Settings', {'fields': ('default_filename', 'is_active')}),
        ('Preview', {'fields': ('has_preview', 'preview_generated_at')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
