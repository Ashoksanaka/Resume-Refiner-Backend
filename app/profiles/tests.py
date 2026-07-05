"""
Integration tests for profile endpoints.

Tests:
- Profile CRUD operations
- Profile validation against JSON schema
- Auth and verification requirements
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from app.authentication.models import User
from app.profiles.models import Profile, ProfileSaveEvent


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def verified_user(db):
    """Create a verified user for testing."""
    user = User.objects.create_user(
        email='test@example.com',
        password='testpass123'
    )
    user.is_verified = True
    user.save()
    return user


@pytest.fixture
def unverified_user(db):
    """Create an unverified user for testing."""
    return User.objects.create_user(
        email='unverified@example.com',
        password='testpass123'
    )


@pytest.fixture
def valid_profile_data():
    """Return valid profile data matching the schema."""
    return {
        'personalInfo': {
            'full_name': 'Jane Doe',
            'email': 'test@example.com',
            'phone_number': '+1-5551234567',
            'location': 'New York, New York, United States',
            'portfolio_url': 'https://jane-doe.dev'
        },
        'summary': 'Innovative software engineer with 5+ years of experience in building scalable applications.',
        'experience': [
            {
                'company': 'TechCorp',
                'title': 'Senior Software Engineer',
                'start_date': '2021-01-15',
                'end_date': None,
                'description': 'Led development of key features and mentored junior engineers.'
            }
        ],
        'education': [
            {
                'institution': 'State University',
                'degree_level': "Bachelor's",
                'course': 'BSc',
                'specialization': 'Computer Science',
                'location': 'California, United States',
                'grade_type': 'cgpa',
                'grade_value': 8.5,
                'start_date': '2012-08-01',
                'end_date': '2016-05-20',
            }
        ],
        'skills': ['Python', 'Django', 'TypeScript', 'React', 'AWS'],
        'certifications': []
    }


@pytest.mark.django_db
class TestProfileGet:
    """Tests for GET /profiles/me"""
    
    def test_get_profile_not_found(self, api_client, verified_user):
        """Test getting profile when none exists returns 404."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.get('/api/v1/profiles/me')
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data['error_code'] == 'NOT_FOUND'
    
    def test_get_profile_success(self, api_client, verified_user, valid_profile_data):
        """Test getting existing profile."""
        # Create profile first
        Profile.objects.create(user=verified_user, data=valid_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.get('/api/v1/profiles/me')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['personalInfo']['full_name'] == 'Jane Doe'
        assert response.data['summary'] == valid_profile_data['summary']
    
    def test_get_profile_unverified_user(self, api_client, unverified_user):
        """Test unverified user cannot access profile."""
        api_client.force_authenticate(user=unverified_user)
        
        response = api_client.get('/api/v1/profiles/me')
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['error_code'] == 'EMAIL_NOT_VERIFIED'
    
    def test_get_profile_unauthenticated(self, api_client):
        """Test unauthenticated request returns 401."""
        response = api_client.get('/api/v1/profiles/me')
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestProfilePut:
    """Tests for PUT /profiles/me"""
    
    def test_create_profile_success(self, api_client, verified_user, valid_profile_data):
        """Test creating a new profile."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.put(
            '/api/v1/profiles/me',
            valid_profile_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['personalInfo']['full_name'] == 'Jane Doe'
        
        # Verify in database
        profile = Profile.objects.get(user=verified_user)
        assert profile.data['personalInfo']['full_name'] == 'Jane Doe'
    
    def test_update_profile_success(self, api_client, verified_user, valid_profile_data):
        """Test updating an existing profile."""
        Profile.objects.create(user=verified_user, data=valid_profile_data)
        
        # Update summary
        updated_data = valid_profile_data.copy()
        updated_data['summary'] = 'Updated summary text here.'
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            updated_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['summary'] == 'Updated summary text here.'
    
    def test_create_profile_invalid_schema(self, api_client, verified_user):
        """Test creating profile with invalid data fails."""
        api_client.force_authenticate(user=verified_user)
        
        invalid_data = {
            'personalInfo': {
                'full_name': 'John Doe'
                # Missing required 'email' field
            },
            'summary': 'Test summary',
            'experience': [],
            'education': [],
            'skills': []
        }
        
        response = api_client.put(
            '/api/v1/profiles/me',
            invalid_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_PAYLOAD'
    
    def test_create_profile_missing_required_fields(self, api_client, verified_user):
        """Test creating profile without required fields fails."""
        api_client.force_authenticate(user=verified_user)
        
        incomplete_data = {
            'personalInfo': {
                'full_name': 'John Doe',
                'email': 'test@example.com',
            },
            # Missing phone_number and location
        }
        
        response = api_client.put(
            '/api/v1/profiles/me',
            incomplete_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestPersonalInfoValidation:
    """Tests for personalInfo field validation."""

    def test_create_profile_invalid_phone(self, api_client, verified_user, valid_profile_data):
        api_client.force_authenticate(user=verified_user)
        invalid_data = valid_profile_data.copy()
        invalid_data['personalInfo'] = {
            **valid_profile_data['personalInfo'],
            'phone_number': '+1-555-123-4567',
        }

        response = api_client.put('/api/v1/profiles/me', invalid_data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_PAYLOAD'

    def test_create_profile_email_mismatch(self, api_client, verified_user, valid_profile_data):
        api_client.force_authenticate(user=verified_user)
        invalid_data = valid_profile_data.copy()
        invalid_data['personalInfo'] = {
            **valid_profile_data['personalInfo'],
            'email': 'other@example.com',
        }

        response = api_client.put('/api/v1/profiles/me', invalid_data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_PAYLOAD'

    def test_create_profile_missing_location(self, api_client, verified_user, valid_profile_data):
        api_client.force_authenticate(user=verified_user)
        invalid_data = valid_profile_data.copy()
        invalid_data['personalInfo'] = {
            'full_name': 'Jane Doe',
            'email': 'test@example.com',
            'phone_number': '+1-5551234567',
        }

        response = api_client.put('/api/v1/profiles/me', invalid_data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_PAYLOAD'

    def test_create_profile_missing_summary(self, api_client, verified_user, valid_profile_data):
        api_client.force_authenticate(user=verified_user)
        invalid_data = valid_profile_data.copy()
        del invalid_data['summary']

        response = api_client.put('/api/v1/profiles/me', invalid_data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_PAYLOAD'

    def test_create_profile_summary_too_short(self, api_client, verified_user, valid_profile_data):
        api_client.force_authenticate(user=verified_user)
        invalid_data = valid_profile_data.copy()
        invalid_data['summary'] = 'Too short'

        response = api_client.put('/api/v1/profiles/me', invalid_data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error_code'] == 'INVALID_PAYLOAD'


@pytest.mark.django_db
class TestProfilePatch:
    """Tests for PATCH /profiles/me"""
    
    def test_patch_profile_success(self, api_client, verified_user, valid_profile_data):
        """Test partial profile update."""
        Profile.objects.create(user=verified_user, data=valid_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'summary': 'New partial summary'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['summary'] == 'New partial summary'
        # Other fields should remain unchanged
        assert response.data['personalInfo']['full_name'] == 'Jane Doe'
    
    def test_patch_nonexistent_profile(self, api_client, verified_user, valid_profile_data):
        """Test patching non-existent profile creates it."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {
                'personalInfo': valid_profile_data['personalInfo'],
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert Profile.objects.filter(user=verified_user).exists()
        assert response.data['personalInfo']['full_name'] == 'Jane Doe'
    
    def test_patch_creates_save_event(self, api_client, verified_user, valid_profile_data):
        """Test patch records a profile save event."""
        Profile.objects.create(user=verified_user, data=valid_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'summary': 'Updated summary for history tracking.'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        event = ProfileSaveEvent.objects.get(user=verified_user)
        assert event.sections == ['summary']


@pytest.mark.django_db
class TestProfileHistory:
    """Tests for GET /profiles/me/history"""

    def test_get_history_returns_latest_three(self, api_client, verified_user, valid_profile_data):
        Profile.objects.create(user=verified_user, data=valid_profile_data)
        api_client.force_authenticate(user=verified_user)

        for index in range(4):
            api_client.patch(
                '/api/v1/profiles/me',
                {'summary': f'Summary version {index} with enough characters.'},
                format='json'
            )

        response = api_client.get('/api/v1/profiles/me/history?limit=3')

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3
        assert response.data[0]['sections'] == ['summary']
        assert 'Updated Summary' in response.data[0]['label']
