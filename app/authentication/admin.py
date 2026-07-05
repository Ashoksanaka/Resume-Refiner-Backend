"""
Django admin configuration for authentication models.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from app.authentication.models import IdempotencyKey, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for the custom User model."""

    list_display = ('email', 'clerk_id', 'is_verified', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('is_verified', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('email', 'clerk_id')
    ordering = ('-date_joined',)

    fieldsets = (
        (None, {'fields': ('email', 'password', 'clerk_id')}),
        ('Verification', {'fields': ('is_verified',)}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'clerk_id', 'is_verified'),
        }),
    )


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    """Admin configuration for IdempotencyKey."""

    list_display = ('key_preview', 'user', 'endpoint', 'response_status', 'created_at', 'expires_at')
    list_filter = ('endpoint', 'response_status')
    search_fields = ('user__email', 'key')
    ordering = ('-created_at',)
    readonly_fields = ('key', 'user', 'endpoint', 'response_status', 'response_body', 'created_at', 'expires_at')

    def key_preview(self, obj):
        return f"{obj.key[:8]}..."
    key_preview.short_description = 'Key'
