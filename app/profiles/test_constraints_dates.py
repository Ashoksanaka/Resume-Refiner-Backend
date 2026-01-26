"""
Tests for date validation constraints.

Tests that dates cannot be in the future (except for ongoing roles),
and that end_date >= start_date where both are present.
"""

import pytest
from datetime import date, timedelta
from rest_framework import status
from rest_framework.test import APIClient
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


@pytest.fixture
def minimal_profile_data():
    return {
        'personalInfo': {
            'full_name': 'John Doe',
            'email': 'john@example.com'
        }
    }


@pytest.mark.django_db
class TestDateConstraints:
    """Tests for date validation constraints."""
    
    def test_future_start_date_rejected(self, api_client, verified_user, minimal_profile_data):
        """Test that start_date in future is rejected."""
        future_date = (date.today() + timedelta(days=1)).isoformat()
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            {
                **minimal_profile_data,
                'experience': [{
                    'company': 'Tech Corp',
                    'title': 'Engineer',
                    'start_date': future_date
                }]
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_future_end_date_rejected(self, api_client, verified_user, minimal_profile_data):
        """Test that end_date in future is rejected."""
        future_date = (date.today() + timedelta(days=1)).isoformat()
        past_date = (date.today() - timedelta(days=365)).isoformat()
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            {
                **minimal_profile_data,
                'experience': [{
                    'company': 'Tech Corp',
                    'title': 'Engineer',
                    'start_date': past_date,
                    'end_date': future_date
                }]
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_end_date_before_start_date_rejected(self, api_client, verified_user, minimal_profile_data):
        """Test that end_date before start_date is rejected."""
        start_date = '2020-01-01'
        end_date = '2019-01-01'
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            {
                **minimal_profile_data,
                'experience': [{
                    'company': 'Tech Corp',
                    'title': 'Engineer',
                    'start_date': start_date,
                    'end_date': end_date
                }]
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_ongoing_project_allows_future_start(self, api_client, verified_user, minimal_profile_data):
        """Test that ongoing projects can have future start_date."""
        future_date = (date.today() + timedelta(days=30)).isoformat()
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            {
                **minimal_profile_data,
                'projects': [{
                    'id': 'project-id',
                    'title': 'Future Project',
                    'role': 'Developer',
                    'start_date': future_date,
                    'ongoing': True
                }]
            },
            format='json'
        )
        
        # Should succeed for ongoing projects
        assert response.status_code == status.HTTP_200_OK
    
    def test_completed_project_rejects_future_start(self, api_client, verified_user, minimal_profile_data):
        """Test that completed projects reject future start_date."""
        future_date = (date.today() + timedelta(days=30)).isoformat()
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            {
                **minimal_profile_data,
                'projects': [{
                    'id': 'project-id',
                    'title': 'Future Project',
                    'role': 'Developer',
                    'start_date': future_date,
                    'ongoing': False
                }]
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_valid_date_range_accepted(self, api_client, verified_user, minimal_profile_data):
        """Test that valid date ranges are accepted."""
        start_date = '2020-01-01'
        end_date = '2022-12-31'
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            {
                **minimal_profile_data,
                'experience': [{
                    'company': 'Tech Corp',
                    'title': 'Engineer',
                    'start_date': start_date,
                    'end_date': end_date
                }]
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
    
    def test_career_break_date_validation(self, api_client, verified_user, minimal_profile_data):
        """Test career break date validation."""
        future_date = (date.today() + timedelta(days=1)).isoformat()
        
        api_client.force_authenticate(user=verified_user)
        response = api_client.put(
            '/api/v1/profiles/me',
            {
                **minimal_profile_data,
                'career_breaks': [{
                    'id': 'break-id',
                    'start_date': future_date,
                    'reason': 'education'
                }]
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
