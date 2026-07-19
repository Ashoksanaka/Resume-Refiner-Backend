"""
Comprehensive CRUD tests for extended profile functionality.

Tests all new profile sections: projects, achievements, areas_of_interest,
hobbies, address, social_urls, profile_picture, volunteering, positions,
career_breaks, licenses, trainings, publications, patents, honors_awards,
test_scores, languages, organizations, contact_info.
"""

import json
from pathlib import Path

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from app.authentication.models import User
from app.profiles.models import Profile


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
def full_profile_data():
    """Load full profile sample from fixture."""
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / 'tests'
        / 'fixtures'
        / 'full_profile_sample.json'
    )
    with fixture_path.open(encoding='utf-8') as fixture:
        return json.load(fixture)


@pytest.mark.django_db
class TestFullProfileCRUD:
    """Tests for full profile CRUD operations with all new sections."""
    
    def test_create_full_profile(self, api_client, verified_user, full_profile_data):
        """Test creating a profile with all sections."""
        api_client.force_authenticate(user=verified_user)
        
        response = api_client.put(
            '/api/v1/profiles/me',
            full_profile_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['personalInfo']['full_name'] == 'Jane Smith'
        assert len(response.data['projects']) == 2
        assert len(response.data['achievements']) == 2
        assert len(response.data['languages']) == 3
        assert response.data['contact_info']['primary_phone'] == '+1-555-123-4567'
    
    def test_get_full_profile(self, api_client, verified_user, full_profile_data):
        """Test getting a profile with all sections."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.get('/api/v1/profiles/me')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'projects' in response.data
        assert 'achievements' in response.data
        assert 'languages' in response.data
        assert 'contact_info' in response.data
        assert response.data['contact_info']['primary_phone'] == '+1-555-123-4567'
    
    def test_update_projects_section(self, api_client, verified_user, full_profile_data):
        """Test updating projects section via PATCH."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        new_project = {
            'id': '550e8400-e29b-41d4-a716-446655440099',
            'title': 'New Project',
            'role': 'Developer',
            'description': 'A newly added project for PATCH coverage.',
            'ongoing': True,
            'technologies': ['python']
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'projects': full_profile_data['projects'] + [new_project]},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['projects']) == 3
    
    def test_update_languages_section(self, api_client, verified_user, full_profile_data):
        """Test updating languages section."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        new_language = {
            'language': 'German',
            'read_proficiency': 'basic',
            'write_proficiency': 'basic',
            'speak_proficiency': 'basic',
            'proficiency': 'basic'
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'languages': full_profile_data['languages'] + [new_language]},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['languages']) == 4
    
    def test_update_social_urls(self, api_client, verified_user, full_profile_data):
        """Test updating social URLs."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        updated_social_urls = {
            'linkedin': 'https://linkedin.com/in/updated',
            'github': 'https://github.com/updated'
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'social_urls': updated_social_urls},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['social_urls']['linkedin'] == 'https://linkedin.com/in/updated'
    
    def test_update_address(self, api_client, verified_user, full_profile_data):
        """Test updating address."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        new_address = {
            'street': '456 New St',
            'city': 'Los Angeles',
            'country': 'USA'
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'address': new_address},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['address']['city'] == 'Los Angeles'
    
    def test_update_contact_info(self, api_client, verified_user, full_profile_data):
        """Test updating contact info."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        new_contact_info = {
            'primary_phone': '+1-555-999-9999',
            'preferred_contact_method': 'phone'
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'contact_info': new_contact_info},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['contact_info']['primary_phone'] == '+1-555-999-9999'
    
    def test_invalid_project_data(self, api_client, verified_user, full_profile_data):
        """Test invalid project data is rejected."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        invalid_project = {
            'id': 'not-a-valid-uuid',
            'title': 'Project without required fields',
            'role': 'Developer',
            'description': 'Invalid because id is not a UUID.',
            'ongoing': False,
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'projects': [invalid_project]},
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_invalid_language_proficiency(self, api_client, verified_user, full_profile_data):
        """Test invalid language proficiency enum is rejected."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        invalid_language = {
            'language': 'French',
            'proficiency': 'invalid_proficiency'  # Not in enum
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'languages': [invalid_language]},
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_invalid_career_break_reason(self, api_client, verified_user, full_profile_data):
        """Test invalid career break reason enum is rejected."""
        Profile.objects.create(user=verified_user, data=full_profile_data)
        
        api_client.force_authenticate(user=verified_user)
        invalid_break = {
            'id': 'break-id',
            'start_date': '2020-01-01',
            'reason': 'invalid_reason'  # Not in enum
        }
        
        response = api_client.patch(
            '/api/v1/profiles/me',
            {'career_breaks': [invalid_break]},
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
