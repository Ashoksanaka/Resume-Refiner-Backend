"""
Tests for AI payload whitelist enforcement.

Tests that only whitelisted profile fields are sent to the AI agent,
and that sensitive fields (contact_info, profile_picture.url, address) are excluded.
"""

import pytest
from app.common.clients.ai_agent import whitelist_profile_for_ai, AI_PROFILE_WHITELIST
from app.authentication.models import User
from app.profiles.models import Profile


@pytest.fixture
def full_profile_data():
    """Full profile data with all sections including sensitive fields."""
    return {
        'personalInfo': {
            'full_name': 'John Doe',
            'email': 'john@example.com',
            'phone_number': '+1-555-123-4567',
            'location': 'New York, USA',
            'portfolio_url': 'https://johndoe.dev'
        },
        'summary': 'Test summary',
        'experience': [{'company': 'Tech Corp', 'title': 'Engineer', 'start_date': '2020-01-01'}],
        'education': [{
            'institution': 'University',
            'degree_level': "Bachelor's",
            'course': 'BSc',
            'specialization': 'Computer Science',
            'location': 'California, United States',
            'grade_type': 'percentage',
            'grade_value': 85,
            'start_date': '2016-01-01',
        }],
        'skills': ['Python', 'Django'],
        'certifications': [],
        'projects': [{'id': 'proj-1', 'title': 'Project', 'role': 'Dev', 'ongoing': False}],
        'achievements': [{'id': 'ach-1', 'title': 'Achievement'}],
        'areas_of_interest': ['AI', 'ML'],
        'hobbies': ['Reading'],
        'address': {
            'street': '123 Main St',
            'city': 'New York',
            'country': 'USA'
        },
        'social_urls': {
            'linkedin': 'https://linkedin.com/in/johndoe',
            'github': 'https://github.com/johndoe'
        },
        'profile_picture': {
            'url': 'https://cdn.example.com/profile.jpg',
            'thumbnail_url': 'https://cdn.example.com/profile_thumb.jpg',
            'uploaded_at': '2024-01-01T00:00:00Z'
        },
        'volunteering': [],
        'positions': [],
        'career_breaks': [],
        'licenses': [],
        'trainings': [],
        'publications': [],
        'patents': [],
        'honors_awards': [],
        'test_scores': [],
        'languages': [{'language': 'English', 'proficiency': 'native'}],
        'organizations': [],
        'contact_info': {
            'primary_phone': '+1-555-123-4567',
            'secondary_phone': '+1-555-987-6543',
            'secondary_email': 'john.personal@example.com',
            'preferred_contact_method': 'email',
            'timezone': 'America/New_York'
        }
    }


@pytest.mark.django_db
class TestAIWhitelist:
    """Tests for AI payload whitelist enforcement."""
    
    def test_contact_info_excluded(self, full_profile_data):
        """Test that contact_info is excluded from AI payload."""
        filtered = whitelist_profile_for_ai(full_profile_data)
        
        assert 'contact_info' not in filtered
    
    def test_profile_picture_url_excluded(self, full_profile_data):
        """Test that profile_picture.url is excluded from AI payload."""
        filtered = whitelist_profile_for_ai(full_profile_data)
        
        assert 'profile_picture' not in filtered
    
    def test_address_excluded(self, full_profile_data):
        """Test that address is excluded from AI payload."""
        filtered = whitelist_profile_for_ai(full_profile_data)
        
        assert 'address' not in filtered
    
    def test_whitelisted_fields_included(self, full_profile_data):
        """Test that whitelisted fields are included."""
        filtered = whitelist_profile_for_ai(full_profile_data)
        
        assert 'personalInfo' in filtered
        assert 'summary' in filtered
        assert 'experience' in filtered
        assert 'education' in filtered
        assert 'skills' in filtered
        assert 'projects' in filtered
        assert 'languages' in filtered
        assert 'social_urls' in filtered
    
    def test_personal_info_filtered(self, full_profile_data):
        """Test that personalInfo subfields are filtered."""
        filtered = whitelist_profile_for_ai(full_profile_data)
        
        personal_info = filtered['personalInfo']
        assert 'full_name' in personal_info
        assert 'email' in personal_info
        assert 'location' in personal_info
        assert 'portfolio_url' in personal_info
        # phone_number should be excluded
        assert 'phone_number' not in personal_info
    
    def test_sensitive_data_not_leaked(self, full_profile_data):
        """Test that no sensitive data leaks through."""
        filtered = whitelist_profile_for_ai(full_profile_data)
        
        # Convert to string to check for any leakage
        filtered_str = str(filtered)
        
        # Check that sensitive data is not present
        assert '+1-555-123-4567' not in filtered_str or 'contact_info' not in filtered
        assert '123 Main St' not in filtered_str or 'address' not in filtered
        assert 'profile.jpg' not in filtered_str or 'profile_picture' not in filtered
    
    def test_only_whitelisted_sections_present(self, full_profile_data):
        """Test that only whitelisted sections are present."""
        filtered = whitelist_profile_for_ai(full_profile_data)
        
        # Check that all keys in filtered are whitelisted
        for key in filtered.keys():
            assert key in AI_PROFILE_WHITELIST, f"Key {key} is not whitelisted"
    
    def test_empty_profile_handled(self):
        """Test that empty profile is handled gracefully."""
        empty_profile = {
            'personalInfo': {
                'full_name': 'John Doe',
                'email': 'john@example.com'
            }
        }
        
        filtered = whitelist_profile_for_ai(empty_profile)
        
        assert 'personalInfo' in filtered
        assert filtered['personalInfo']['full_name'] == 'John Doe'
