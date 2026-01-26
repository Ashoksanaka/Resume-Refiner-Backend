"""
Django admin configuration for authentication models.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from app.authentication.models import User, EmailVerificationToken, IdempotencyKey


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for the custom User model."""
    
    list_display = ('email', 'is_verified', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('is_verified', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('email',)
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Verification', {'fields': ('is_verified',)}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'is_verified'),
        }),
    )


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    """Admin configuration for EmailVerificationToken."""
    
    list_display = ('user', 'token_preview', 'created_at', 'expires_at', 'is_used')
    list_filter = ('used_at',)
    search_fields = ('user__email',)
    ordering = ('-created_at',)
    readonly_fields = ('token', 'created_at', 'expires_at', 'used_at')
    
    def token_preview(self, obj):
        """Show only the first 8 characters of the token."""
        return f"{obj.token[:8]}..."
    token_preview.short_description = 'Token'
    
    def is_used(self, obj):
        return obj.used_at is not None
    is_used.boolean = True
    is_used.short_description = 'Used'


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    """Admin configuration for IdempotencyKey."""
    
    list_display = ('key_preview', 'user', 'endpoint', 'response_status', 'created_at', 'expires_at')
    list_filter = ('endpoint', 'response_status')
    search_fields = ('user__email', 'key')
    ordering = ('-created_at',)
    readonly_fields = ('key', 'user', 'endpoint', 'response_status', 'response_body', 'created_at', 'expires_at')
    
    def key_preview(self, obj):
        """Show only the first 8 characters of the key."""
        return f"{obj.key[:8]}..."
    key_preview.short_description = 'Key'
