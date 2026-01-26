"""
Django admin configuration for profile models.
"""

from django.contrib import admin
from app.profiles.models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Admin configuration for Profile model."""
    
    list_display = ('user', 'full_name', 'created_at', 'updated_at')
    search_fields = ('user__email',)
    ordering = ('-updated_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    def full_name(self, obj):
        """Extract full name from profile data."""
        return obj.data.get('personalInfo', {}).get('full_name', 'N/A')
    full_name.short_description = 'Full Name'
    
    fieldsets = (
        ('User', {'fields': ('user',)}),
        ('Profile Data', {'fields': ('data',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
