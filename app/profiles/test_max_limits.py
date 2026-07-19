"""
Tests for maximum array length limits.

Tests that arrays exceeding allowed lengths are rejected to prevent DoS attacks.
"""

import uuid

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from app.authentication.models import User


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
def minimal_profile_data(verified_user):
    return {
        'personalInfo': {
            'full_name': 'John Doe',
            'email': verified_user.email,
            'phone_number': '+1-5551234567',
            'location': 'New York, USA',
        },
        'summary': 'Experienced software engineer with expertise in full-stack development.',
    }


def _project(i: int) -> dict:
    return {
        'id': str(uuid.uuid4()),
        'title': f'Project {i}',
        'role': 'Developer',
        'description': f'Description for project {i}.',
        'ongoing': False,
    }


def _experience(i: int) -> dict:
    return {
        'company': f'Company {i}',
        'title': 'Engineer',
        'start_date': '2020-01-01',
        'description': f'Description for role {i}.',
    }


@pytest.mark.django_db
class TestMaxLimits:
    """Tests for maximum array length limits."""

    def test_projects_max_limit(self, api_client, verified_user, minimal_profile_data):
        """Test that projects array exceeding 50 items is rejected."""
        api_client.force_authenticate(user=verified_user)

        response = api_client.put(
            '/api/v1/profiles/me',
            {**minimal_profile_data, 'projects': [_project(i) for i in range(51)]},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_skills_max_limit(self, api_client, verified_user, minimal_profile_data):
        """Test that skills array exceeding 50 items is rejected."""
        api_client.force_authenticate(user=verified_user)

        response = api_client.put(
            '/api/v1/profiles/me',
            {**minimal_profile_data, 'skills': [f'Skill {i}' for i in range(51)]},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_experience_max_limit(self, api_client, verified_user, minimal_profile_data):
        """Test that experience array exceeding 25 items is rejected."""
        api_client.force_authenticate(user=verified_user)

        response = api_client.put(
            '/api/v1/profiles/me',
            {**minimal_profile_data, 'experience': [_experience(i) for i in range(26)]},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_publications_max_limit(self, api_client, verified_user, minimal_profile_data):
        """Test that publications array exceeding 50 items is rejected."""
        api_client.force_authenticate(user=verified_user)

        publications = [
            {
                'id': str(uuid.uuid4()),
                'title': f'Publication {i}',
                'authors': [{'name': 'Author', 'order': 1}],
                'venue': 'Venue',
                'date': '2020-01-01',
            }
            for i in range(51)
        ]

        response = api_client.put(
            '/api/v1/profiles/me',
            {**minimal_profile_data, 'publications': publications},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_career_breaks_max_limit(self, api_client, verified_user, minimal_profile_data):
        """Test that career_breaks array exceeding 20 items is rejected."""
        api_client.force_authenticate(user=verified_user)

        career_breaks = [
            {
                'id': str(uuid.uuid4()),
                'start_date': '2020-01-01',
                'reason': 'education',
                'description': f'Career break {i} for education.',
            }
            for i in range(21)
        ]

        response = api_client.put(
            '/api/v1/profiles/me',
            {**minimal_profile_data, 'career_breaks': career_breaks},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_valid_limits_accepted(self, api_client, verified_user, minimal_profile_data):
        """Test that arrays within limits are accepted."""
        api_client.force_authenticate(user=verified_user)

        data = {
            **minimal_profile_data,
            'projects': [_project(i) for i in range(50)],
            'skills': [f'Skill {i}' for i in range(50)],
            'experience': [_experience(i) for i in range(25)],
        }

        response = api_client.put(
            '/api/v1/profiles/me',
            data,
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
