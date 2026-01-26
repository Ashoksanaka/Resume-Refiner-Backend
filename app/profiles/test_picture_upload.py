"""
Tests for profile picture upload functionality.

Tests upload, thumbnail generation, and deletion of profile pictures.
"""

import pytest
import io
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile
from app.authentication.models import User
from app.profiles.models import Profile


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def verified_user(db):
    user = User.objects.create_user(email='test@example.com', password='testpass123')
    user.is_verified = True
    user.save()
    return user


def create_test_image(filename='test.jpg', size=(100, 100)):
    """Create a test image file."""
    img = Image.new('RGB', size, color='red')
    img_io = io.BytesIO()
    img.save(img_io, format='JPEG')
    img_io.seek(0)
    return SimpleUploadedFile(filename, img_io.read(), content_type='image/jpeg')


@pytest.mark.django_db
class TestPictureUpload:
    """Tests for profile picture upload."""
    
    def test_upload_picture_success(self, api_client, verified_user):
        """Test successful picture upload."""
        api_client.force_authenticate(user=verified_user)
        
        image = create_test_image('profile.jpg')
        response = api_client.post(
            '/api/v1/profiles/me/picture',
            {'file': image},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'profile_picture' in response.data
        assert 'url' in response.data['profile_picture']
        assert 'thumbnail_url' in response.data['profile_picture']
        assert 'uploaded_at' in response.data['profile_picture']
    
    def test_upload_picture_invalid_type(self, api_client, verified_user):
        """Test that non-image files are rejected."""
        api_client.force_authenticate(user=verified_user)
        
        text_file = SimpleUploadedFile('test.txt', b'not an image', content_type='text/plain')
        response = api_client.post(
            '/api/v1/profiles/me/picture',
            {'file': text_file},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_upload_picture_missing_file(self, api_client, verified_user):
        """Test that missing file field is rejected."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.post(
            '/api/v1/profiles/me/picture',
            {},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_upload_picture_large_file(self, api_client, verified_user):
        """Test that files exceeding size limit are rejected."""
        api_client.force_authenticate(user=verified_user)
        
        # Create a large image (simulate by creating a file that's too large)
        large_file = SimpleUploadedFile(
            'large.jpg',
            b'x' * (6 * 1024 * 1024),  # 6MB
            content_type='image/jpeg'
        )
        
        response = api_client.post(
            '/api/v1/profiles/me/picture',
            {'file': large_file},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_delete_picture_success(self, api_client, verified_user):
        """Test successful picture deletion."""
        # First upload a picture
        api_client.force_authenticate(user=verified_user)
        image = create_test_image('profile.jpg')
        upload_response = api_client.post(
            '/api/v1/profiles/me/picture',
            {'file': image},
            format='multipart'
        )
        assert upload_response.status_code == status.HTTP_200_OK
        
        # Then delete it
        delete_response = api_client.delete('/api/v1/profiles/me/picture')
        
        assert delete_response.status_code == status.HTTP_200_OK
        assert delete_response.data.get('profile_picture') is None
    
    def test_delete_picture_when_none_exists(self, api_client, verified_user):
        """Test deleting picture when none exists."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.delete('/api/v1/profiles/me/picture')
        
        # Should succeed even if no picture exists
        assert response.status_code == status.HTTP_200_OK
    
    def test_upload_png_image(self, api_client, verified_user):
        """Test that PNG images are accepted."""
        api_client.force_authenticate(user=verified_user)
        
        # Create PNG image
        img = Image.new('RGB', (100, 100), color='blue')
        img_io = io.BytesIO()
        img.save(img_io, format='PNG')
        img_io.seek(0)
        png_file = SimpleUploadedFile('test.png', img_io.read(), content_type='image/png')
        
        response = api_client.post(
            '/api/v1/profiles/me/picture',
            {'file': png_file},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'profile_picture' in response.data
    
    def test_picture_stored_in_profile_data(self, api_client, verified_user):
        """Test that picture URLs are stored in profile data."""
        api_client.force_authenticate(user=verified_user)
        
        image = create_test_image('profile.jpg')
        response = api_client.post(
            '/api/v1/profiles/me/picture',
            {'file': image},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_200_OK
        
        # Verify in database
        profile = Profile.objects.get(user=verified_user)
        assert 'profile_picture' in profile.data
        assert 'url' in profile.data['profile_picture']
        assert 'thumbnail_url' in profile.data['profile_picture']
