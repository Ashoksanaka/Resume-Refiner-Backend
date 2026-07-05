"""
Serializers for authentication endpoints.
"""

from rest_framework import serializers

from app.authentication.models import User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for the authenticated user response."""

    class Meta:
        model = User
        fields = ['id', 'email', 'is_verified']
        read_only_fields = ['id', 'is_verified']
