"""
Profile API views for the Resume AI platform.

Implements the profile endpoints as per OpenAPI spec:
- GET /profiles/me
- PUT /profiles/me
- PATCH /profiles/me
- POST /profiles/me/picture
- DELETE /profiles/me/picture
"""

import logging
import uuid
import os
from datetime import datetime
from pathlib import Path
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from PIL import Image
from io import BytesIO
from app.profiles.serializers import (
    ProfileSerializer,
    ProfileCreateUpdateSerializer,
    ProfileSaveEventSerializer,
)
from app.profiles.services import ProfileService
from app.authentication.services import AuthenticationService
from app.common.exceptions import InvalidPayloadException, ResourceNotFoundException

logger = logging.getLogger(__name__)


class ProfileView(APIView):
    """
    GET, PUT, PATCH /profiles/me
    
    Manage the current user's profile.
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        GET /profiles/me
        
        Get the current user's profile.
        
        SECURITY: contact_info is redacted unless request.user is the profile owner.
        
        Response: 200 OK with Profile object
        Response: 404 Not Found if no profile exists
        """
        # Require verified email
        AuthenticationService.require_verified_email(request.user)
        
        try:
            profile = ProfileService.get_profile(request.user)
        except ResourceNotFoundException:
            return Response(
                {
                    'error_code': 'NOT_FOUND',
                    'message': 'Profile not found. Please create a profile first.',
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = ProfileSerializer(profile)
        data = serializer.data
        
        # Redact contact_info if user is not the profile owner
        # (In this case, user is always the owner since we get by request.user)
        # But keeping the logic for future extensibility
        if profile.user != request.user:
            data['contact_info'] = None
        
        return Response(data, status=status.HTTP_200_OK)
    
    def put(self, request):
        """
        PUT /profiles/me
        
        Create or replace the user's profile.
        
        Request: Full Profile object
        Response: 200 OK with updated Profile
        """
        # Require verified email
        AuthenticationService.require_verified_email(request.user)
        
        serializer = ProfileCreateUpdateSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        # Create or fully replace the profile
        profile = ProfileService.create_or_update_profile(
            user=request.user,
            data=serializer.validated_data,
            partial=False
        )
        
        ProfileService.record_save_event(
            user=request.user,
            sections=list(serializer.validated_data.keys()),
        )
        
        serializer = ProfileSerializer(profile)
        data = serializer.data
        
        # Redact contact_info if user is not the profile owner
        if profile.user != request.user:
            data['contact_info'] = None
        
        return Response(data, status=status.HTTP_200_OK)
    
    def patch(self, request):
        """
        PATCH /profiles/me
        
        Partially update the user's profile.
        
        Request: Partial Profile object
        Response: 200 OK with updated Profile
        """
        # Require verified email
        AuthenticationService.require_verified_email(request.user)
        
        serializer = ProfileCreateUpdateSerializer(
            data=request.data,
            context={'request': request},
            partial=True
        )
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        # Partially update the profile (creates profile if missing)
        profile = ProfileService.create_or_update_profile(
            user=request.user,
            data=serializer.validated_data,
            partial=True
        )
        
        ProfileService.record_save_event(
            user=request.user,
            sections=list(serializer.validated_data.keys()),
        )
        
        serializer = ProfileSerializer(profile)
        data = serializer.data
        
        # Redact contact_info if user is not the profile owner
        if profile.user != request.user:
            data['contact_info'] = None
        
        return Response(data, status=status.HTTP_200_OK)


class ProfileHistoryView(APIView):
    """
    GET /profiles/me/history
    
    List recent profile save events for the current user.
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        GET /profiles/me/history?limit=3
        
        Response: 200 OK with array of save events
        """
        AuthenticationService.require_verified_email(request.user)
        
        try:
            limit = int(request.query_params.get('limit', 3))
        except (TypeError, ValueError):
            limit = 3
        
        events = ProfileService.get_save_history(request.user, limit=limit)
        serializer = ProfileSaveEventSerializer(events, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProfilePictureView(APIView):
    """
    POST, DELETE /profiles/me/picture
    
    Manage the current user's profile picture.
    """
    
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    # Allowed image content types
    ALLOWED_CONTENT_TYPES = ['image/jpeg', 'image/png', 'image/jpg']
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    
    def post(self, request):
        """
        POST /profiles/me/picture
        
        Upload a profile picture.
        
        Request: multipart/form-data with 'file' field
        Response: 200 OK with updated profile including picture URLs
        
        SECURITY:
        - Validates content type (JPEG/PNG only)
        - Validates file size (max 5MB)
        - Generates thumbnails (128x128 and 512x512)
        - Stores in object storage (S3 compatible)
        """
        # Require verified email
        AuthenticationService.require_verified_email(request.user)
        
        if 'file' not in request.FILES:
            raise InvalidPayloadException(
                message='Missing file field in request.',
            )
        
        file = request.FILES['file']
        
        # Validate content type
        if file.content_type not in self.ALLOWED_CONTENT_TYPES:
            raise InvalidPayloadException(
                message=f'Invalid file type. Allowed types: JPEG, PNG.',
            )
        
        # Validate file size
        if file.size > self.MAX_FILE_SIZE:
            raise InvalidPayloadException(
                message=f'File too large. Maximum size: {self.MAX_FILE_SIZE / (1024 * 1024)}MB.',
            )
        
        try:
            # Get or create profile
            profile, _ = ProfileService.get_or_create_profile(request.user)
            
            # Read image
            image = Image.open(file)
            image = image.convert('RGB')  # Convert to RGB for JPEG compatibility
            
            # Generate unique filename
            file_ext = 'jpg'
            filename = f"profiles/{request.user.id}/{uuid.uuid4()}.{file_ext}"
            
            # Save original (512x512 max)
            if image.width > 512 or image.height > 512:
                image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            
            original_buffer = BytesIO()
            image.save(original_buffer, format='JPEG', quality=85)
            original_buffer.seek(0)
            
            # Generate thumbnail (128x128)
            thumbnail_image = image.copy()
            thumbnail_image.thumbnail((128, 128), Image.Resampling.LANCZOS)
            thumbnail_buffer = BytesIO()
            thumbnail_image.save(thumbnail_buffer, format='JPEG', quality=85)
            thumbnail_buffer.seek(0)
            
            # Store files (using default storage - can be configured for S3)
            # In production, replace with S3-compatible storage
            original_path = default_storage.save(filename, ContentFile(original_buffer.read()))
            thumbnail_filename = filename.replace(f'.{file_ext}', f'_thumb.{file_ext}')
            thumbnail_path = default_storage.save(thumbnail_filename, ContentFile(thumbnail_buffer.read()))
            
            # Get URLs (in production, these would be CDN URLs)
            original_url = default_storage.url(original_path)
            thumbnail_url = default_storage.url(thumbnail_path)
            
            # Update profile data
            profile_data = profile.data or {}
            profile_data['profile_picture'] = {
                'url': original_url,
                'thumbnail_url': thumbnail_url,
                'uploaded_at': datetime.utcnow().isoformat() + 'Z'
            }
            profile.data = profile_data
            profile.save()
            
            serializer = ProfileSerializer(profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error("Error uploading profile picture: %s", str(e))
            raise InvalidPayloadException(
                message='Failed to upload profile picture.',
            )
    
    def delete(self, request):
        """
        DELETE /profiles/me/picture
        
        Delete the current user's profile picture.
        
        Response: 200 OK with updated profile
        """
        # Require verified email
        AuthenticationService.require_verified_email(request.user)
        
        try:
            profile = ProfileService.get_profile(request.user)
        except ResourceNotFoundException:
            raise InvalidPayloadException(
                message='Profile not found.',
            )
        
        # Remove profile picture from data
        profile_data = profile.data or {}
        if 'profile_picture' in profile_data:
            # Optionally delete files from storage
            picture_data = profile_data['profile_picture']
            if 'url' in picture_data:
                try:
                    # Extract path from URL and delete
                    url_path = picture_data['url']
                    if url_path.startswith('/'):
                        # Local file path
                        default_storage.delete(url_path.lstrip('/'))
                    if 'thumbnail_url' in picture_data:
                        thumb_path = picture_data['thumbnail_url']
                        if thumb_path.startswith('/'):
                            default_storage.delete(thumb_path.lstrip('/'))
                except Exception as e:
                    logger.warning("Failed to delete picture files: %s", str(e))
            
            del profile_data['profile_picture']
            profile.data = profile_data
            profile.save()
        
        serializer = ProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)
