"""
Integration tests for common functionality.

Tests:
- TTL cleanup task
- Error handling
"""

import pytest
from datetime import timedelta
from django.utils import timezone
from app.authentication.models import User, IdempotencyKey
from app.profiles.models import Profile
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.common.models import Template
from app.common.tasks import cleanup_expired_resources
from app.authentication.tasks import cleanup_expired_tokens, cleanup_expired_idempotency_keys


@pytest.fixture
def verified_user(db):
    """Create a verified user with a profile."""
    user = User.objects.create_user(
        email='test@example.com',
        password='testpass123'
    )
    user.is_verified = True
    user.save()
    
    profile_data = {
        'personalInfo': {'full_name': 'Test User', 'email': 'test@example.com'},
        'summary': 'Test summary',
        'experience': [],
        'education': [],
        'skills': []
    }
    Profile.objects.create(user=user, data=profile_data)
    return user


@pytest.fixture
def template(db):
    """Create a template."""
    return Template.objects.create(
        id='test-template',
        name='Test Template',
        latex_file='test.tex',
        is_active=True
    )


@pytest.mark.django_db
class TestTTLCleanup:
    """Tests for TTL cleanup functionality."""
    
    def test_cleanup_expired_job_descriptions(self, verified_user):
        """Test that expired JDs are deleted."""
        # Create an expired JD
        expired_jd = JobDescription.objects.create(
            user=verified_user,
            role_name='Expired Role',
            text='Expired job description',
            expires_at=timezone.now() - timedelta(hours=1)
        )
        
        # Create a valid JD
        valid_jd = JobDescription.objects.create(
            user=verified_user,
            role_name='Valid Role',
            text='Valid job description',
            expires_at=timezone.now() + timedelta(hours=23)
        )
        
        # Run cleanup
        result = cleanup_expired_resources()
        
        # Verify expired JD is deleted
        assert not JobDescription.objects.filter(id=expired_jd.id).exists()
        # Verify valid JD still exists
        assert JobDescription.objects.filter(id=valid_jd.id).exists()
        assert result['job_descriptions_deleted'] == 1
    
    def test_cleanup_expired_resume_requests(self, verified_user, template):
        """Test that expired resume requests are deleted."""
        # Create a JD first
        jd = JobDescription.objects.create(
            user=verified_user,
            role_name='Test Role',
            text='Test JD',
            expires_at=timezone.now() + timedelta(hours=24)
        )
        
        # Create an expired resume request
        expired_request = ResumeGenerationRequest.objects.create(
            user=verified_user,
            job_description=jd,
            template_id=template.id,
            profile_snapshot={},
            expires_at=timezone.now() - timedelta(hours=1)
        )
        
        # Create a valid resume request
        valid_request = ResumeGenerationRequest.objects.create(
            user=verified_user,
            job_description=jd,
            template_id=template.id,
            profile_snapshot={},
            expires_at=timezone.now() + timedelta(hours=23)
        )
        
        # Run cleanup
        result = cleanup_expired_resources()
        
        # Verify expired request is deleted
        assert not ResumeGenerationRequest.objects.filter(id=expired_request.id).exists()
        # Verify valid request still exists
        assert ResumeGenerationRequest.objects.filter(id=valid_request.id).exists()
        assert result['resume_requests_deleted'] == 1
    
    def test_cleanup_expired_tokens_noop(self, verified_user):
        """Legacy token cleanup task is a no-op after Clerk migration."""
        result = cleanup_expired_tokens()
        assert result['skipped'] is True
    
    def test_cleanup_expired_idempotency_keys(self, verified_user):
        """Test that expired idempotency keys are deleted."""
        # Create an expired key
        expired_key = IdempotencyKey.objects.create(
            user=verified_user,
            key='expired-key',
            endpoint='POST /resumes',
            response_status=202,
            response_body={},
            expires_at=timezone.now() - timedelta(hours=1)
        )
        
        # Create a valid key
        valid_key = IdempotencyKey.objects.create(
            user=verified_user,
            key='valid-key',
            endpoint='POST /resumes',
            response_status=202,
            response_body={},
            expires_at=timezone.now() + timedelta(hours=23)
        )
        
        # Run cleanup
        result = cleanup_expired_idempotency_keys()
        
        # Verify expired key is deleted
        assert not IdempotencyKey.objects.filter(id=expired_key.id).exists()
        # Verify valid key still exists
        assert IdempotencyKey.objects.filter(id=valid_key.id).exists()
        assert result['idempotency_keys_deleted'] == 1


@pytest.mark.django_db
class TestTTLExpiration:
    """Tests for TTL expiration behavior."""
    
    def test_job_description_is_expired_property(self, verified_user):
        """Test JD is_expired property."""
        # Create an expired JD
        expired_jd = JobDescription.objects.create(
            user=verified_user,
            role_name='Expired Role',
            text='Expired',
            expires_at=timezone.now() - timedelta(hours=1)
        )
        
        # Create a valid JD
        valid_jd = JobDescription.objects.create(
            user=verified_user,
            role_name='Valid Role',
            text='Valid',
            expires_at=timezone.now() + timedelta(hours=23)
        )
        
        assert expired_jd.is_expired is True
        assert valid_jd.is_expired is False
    
    def test_resume_request_is_expired_property(self, verified_user, template):
        """Test ResumeGenerationRequest is_expired property."""
        jd = JobDescription.objects.create(
            user=verified_user,
            role_name='Test Role',
            text='Test',
            expires_at=timezone.now() + timedelta(hours=24)
        )
        
        expired_request = ResumeGenerationRequest.objects.create(
            user=verified_user,
            job_description=jd,
            template_id=template.id,
            profile_snapshot={},
            expires_at=timezone.now() - timedelta(hours=1)
        )
        
        valid_request = ResumeGenerationRequest.objects.create(
            user=verified_user,
            job_description=jd,
            template_id=template.id,
            profile_snapshot={},
            expires_at=timezone.now() + timedelta(hours=23)
        )
        
        assert expired_request.is_expired is True
        assert valid_request.is_expired is False
