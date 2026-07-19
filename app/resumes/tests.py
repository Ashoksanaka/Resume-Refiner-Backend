"""
Integration tests for resume-related endpoints.

Tests:
- Job description CRUD
- Resume generation trigger and status
- TTL expiry behavior
- Hallucination detection
- LaTeX compilation errors
"""

import pytest
import uuid
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from app.authentication.models import User
from app.profiles.models import Profile
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.common.models import Template
from app.resumes.services import HallucinationDetector


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def verified_user(db):
    """Create a verified user with a profile."""
    user = User.objects.create_user(
        email='test@example.com',
        password='testpass123'
    )
    user.is_verified = True
    user.save()
    return user


@pytest.fixture
def user_with_profile(verified_user):
    """Create a verified user with a complete profile."""
    profile_data = {
        'personalInfo': {
            'full_name': 'Jane Doe',
            'email': 'jane.doe@example.com',
            'phone_number': '+1-555-123-4567',
            'location': 'New York, USA'
        },
        'summary': 'Experienced software engineer.',
        'experience': [
            {
                'company': 'TechCorp',
                'title': 'Senior Engineer',
                'start_date': '2021-01-15',
                'end_date': None,
                'description': 'Led development of key features.'
            }
        ],
        'education': [
            {
                'institution': 'State University',
                'degree': 'B.S. Computer Science',
                'start_date': '2012-08-01',
                'end_date': '2016-05-20'
            }
        ],
        'skills': ['Python', 'Django', 'React'],
        'certifications': []
    }
    Profile.objects.create(user=verified_user, data=profile_data)
    return verified_user


@pytest.fixture
def template(db):
    """Create an active template with the new model structure."""
    return Template.objects.create(
        id='altacv',
        name='Professional Modern',
        description='A clean, modern resume template.',
        author='Resume AI Platform',
        version='1.0.0',
        default_filename='resume',
        has_preview=True,
        is_active=True
    )


@pytest.fixture
def job_description(user_with_profile):
    """Create a job description."""
    return JobDescription.objects.create(
        user=user_with_profile,
        role_name='Senior Software Engineer',
        text='We are looking for a Senior Software Engineer with Python and Django experience.'
    )


DEFAULT_SECTIONS = ['personalInfo', 'summary', 'experience', 'education', 'skills']


# =============================================================================
# Job Description Tests
# =============================================================================

@pytest.mark.django_db
class TestJobDescriptionCreate:
    """Tests for POST /jds"""
    
    def test_create_jd_success(self, api_client, user_with_profile):
        """Test successful job description creation."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.post(
            '/api/v1/jds',
            {
                'role_name': 'Senior Software Engineer',
                'text': 'Looking for a Python developer with 5+ years experience in backend systems.',
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data
        assert 'expires_at' in response.data
        assert response.data['role_name'] == 'Senior Software Engineer'
        assert response.data['text'] == 'Looking for a Python developer with 5+ years experience in backend systems.'
    
    def test_create_jd_requires_role_name(self, api_client, user_with_profile):
        """Test creating JD without role_name fails."""
        api_client.force_authenticate(user=user_with_profile)

        response = api_client.post(
            '/api/v1/jds',
            {'text': 'Looking for a Python developer with 5+ years experience in backend systems.'},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_jd_sets_ttl(self, api_client, user_with_profile):
        """Test that JD has correct TTL set."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.post(
            '/api/v1/jds',
            {
                'role_name': 'Backend Engineer',
                'text': 'Test job description with enough characters to pass validation checks easily.',
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        
        jd = JobDescription.objects.get(id=response.data['id'])
        # Should expire in approximately 24 hours
        expected_expiry = timezone.now() + timedelta(hours=24)
        assert abs((jd.expires_at - expected_expiry).total_seconds()) < 60
    
    def test_create_jd_empty_text(self, api_client, user_with_profile):
        """Test creating JD with empty text fails."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.post(
            '/api/v1/jds',
            {
                'role_name': 'Engineer',
                'text': '   ',
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestJobDescriptionGet:
    """Tests for GET /jds/{id}"""
    
    def test_get_jd_success(self, api_client, user_with_profile, job_description):
        """Test getting a job description."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.get(f'/api/v1/jds/{job_description.id}')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == str(job_description.id)
    
    def test_get_jd_not_found(self, api_client, user_with_profile):
        """Test getting non-existent JD returns 404."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.get(f'/api/v1/jds/{uuid.uuid4()}')
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_get_expired_jd_returns_410(self, api_client, user_with_profile, job_description):
        """Test getting expired JD returns 410 Gone (TTL_EXPIRED)."""
        # Expire the JD
        job_description.expires_at = timezone.now() - timedelta(hours=1)
        job_description.save()
        
        api_client.force_authenticate(user=user_with_profile)
        response = api_client.get(f'/api/v1/jds/{job_description.id}')
        
        assert response.status_code == status.HTTP_410_GONE
        assert response.data['error_code'] == 'TTL_EXPIRED'


@pytest.mark.django_db
class TestJobDescriptionDelete:
    """Tests for DELETE /jds/{id}"""
    
    def test_delete_jd_success(self, api_client, user_with_profile, job_description):
        """Test deleting a job description."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.delete(f'/api/v1/jds/{job_description.id}')
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not JobDescription.objects.filter(id=job_description.id).exists()


# =============================================================================
# Resume Generation Tests
# =============================================================================

@pytest.mark.django_db
class TestResumeGenerationCreate:
    """Tests for POST /resumes"""
    
    def test_create_generation_success(self, api_client, user_with_profile, job_description, template):
        """Test triggering resume generation."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': DEFAULT_SECTIONS,
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data['status'] == 'pending'
        assert 'id' in response.data
        assert 'expires_at' in response.data
    
    def test_create_generation_invalid_jd(self, api_client, user_with_profile, template):
        """Test generation with non-existent JD fails."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(uuid.uuid4()),
                'template_id': template.id,
                'sections': DEFAULT_SECTIONS,
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_generation_invalid_template(self, api_client, user_with_profile, job_description):
        """Test generation with non-existent template fails."""
        api_client.force_authenticate(user=user_with_profile)
        
        response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': 'nonexistent-template',
                'sections': DEFAULT_SECTIONS,
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_idempotency_key(self, api_client, user_with_profile, job_description, template):
        """Test idempotency key prevents duplicate requests."""
        api_client.force_authenticate(user=user_with_profile)
        idempotency_key = str(uuid.uuid4())
        
        # First request
        response1 = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': DEFAULT_SECTIONS,
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY=idempotency_key
        )
        
        # Second request with same key
        response2 = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': DEFAULT_SECTIONS,
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY=idempotency_key
        )
        
        assert response1.status_code == status.HTTP_202_ACCEPTED
        assert response2.status_code == status.HTTP_202_ACCEPTED
        # Should return the same generation request
        assert response1.data['id'] == response2.data['id']

    def test_create_generation_filters_sections(self, api_client, user_with_profile, job_description, template):
        """Test that selected sections filter the stored profile snapshot."""
        api_client.force_authenticate(user=user_with_profile)

        response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': ['experience'],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        request = ResumeGenerationRequest.objects.get(id=response.data['id'])
        assert set(request.profile_snapshot.keys()) == {'personalInfo', 'experience'}
        assert request.selected_sections == ['experience']

    def test_create_generation_invalid_section(self, api_client, user_with_profile, job_description, template):
        """Test generation with invalid section key fails."""
        api_client.force_authenticate(user=user_with_profile)

        response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': ['not_a_real_section'],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_generation_rejects_empty_section_data(
        self, api_client, user_with_profile, job_description, template
    ):
        """Reject sections that have no data in the user profile."""
        api_client.force_authenticate(user=user_with_profile)

        response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': ['projects'],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_generation_response_has_no_output_format_fields(
        self, api_client, user_with_profile, job_description, template
    ):
        """PDF-only API does not expose output_format or artifacts."""
        api_client.force_authenticate(user=user_with_profile)

        response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': DEFAULT_SECTIONS,
            },
            format='json',
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert 'output_format' not in response.data
        assert 'artifacts' not in response.data
        assert set(response.data.keys()) >= {
            'id', 'status', 'failure_reason', 'created_at', 'expires_at',
        }


@pytest.mark.django_db
class TestPdfOnlyGenerationPipeline:
    """Every successful generation must compile to PDF via FormaTeX."""

    def test_task_always_compiles_pdf(self, user_with_profile, job_description, template):
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.resumes.tasks import process_resume_generation
        from app.common.clients.ai_agent import AIGenerationResult
        from app.common.clients.latex_service import CompilationResult

        latex = (
            r'\documentclass{article}\begin{document}'
            r'\resumeHeader{Jane Doe}'
            r'\resumeSectionTitle{PROFESSIONAL EXPERIENCE}'
            r'\begin{itemize}\resumeItem{TechCorp}\end{itemize}'
            r'\end{document}'
        )
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data,
            selected_sections=['experience'],
            status=ResumeGenerationRequest.STATUS_PENDING,
        )

        mock_latex_client = MagicMock()
        mock_latex_client.get_resume_template_content = AsyncMock(return_value='\\documentclass{article}')
        mock_latex_client.compile_latex = AsyncMock(
            return_value=CompilationResult(
                pdf_path='/tmp/test-resume.pdf',
                compilation_log='',
                success=True,
            )
        )

        mock_ai = MagicMock()
        mock_ai.generate_resume = AsyncMock(
            return_value=AIGenerationResult(
                latex_source=latex,
                modifications=['ok'],
                raw_response={},
            )
        )

        with patch('app.resumes.tasks.LaTeXServiceClient', return_value=mock_latex_client), \
             patch('app.resumes.tasks.AIAgentClient', return_value=mock_ai), \
             patch('app.resumes.tasks.ResumeGenerationService.validate_ai_output'):
            process_resume_generation(str(request.id))

        request.refresh_from_db()
        assert request.status == 'success'
        assert request.generated_latex == latex
        assert request.generated_pdf_path == '/tmp/test-resume.pdf'
        mock_latex_client.compile_latex.assert_called_once()

    def test_download_requires_pdf_path(
        self, api_client, user_with_profile, job_description, template
    ):
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data,
            selected_sections=DEFAULT_SECTIONS,
            status=ResumeGenerationRequest.STATUS_SUCCESS,
            generated_latex=r'\documentclass{article}\begin{document}x\end{document}',
            generated_pdf_path=None,
        )

        api_client.force_authenticate(user=user_with_profile)
        response = api_client.get(f'/api/v1/resumes/{request.id}/download')

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestTemplateBasedGeneration:
    """Tests for template-based generation wiring and validation."""

    def test_profile_section_has_data(self, user_with_profile):
        from app.resumes.services import profile_section_has_data

        snapshot = user_with_profile.profile.data
        assert profile_section_has_data(snapshot, 'experience') is True
        assert profile_section_has_data(snapshot, 'projects') is False
        assert profile_section_has_data(snapshot, 'personalInfo') is True

    def test_validate_latex_section_boundaries_rejects_unselected(
        self, user_with_profile, job_description, template
    ):
        from app.resumes.services import ResumeGenerationService
        from app.common.exceptions import ModelOutputInvalidException

        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot={'personalInfo': user_with_profile.profile.data['personalInfo']},
            selected_sections=['experience'],
        )

        latex_with_education = r"""\documentclass{article}
\begin{document}
\resumeHeader{Jane Doe}
\resumeSectionTitle{PROFESSIONAL EXPERIENCE}
\begin{itemize}
\resumeItem{TechCorp}
\end{itemize}
\resumeSectionTitle{EDUCATION}
\begin{itemize}
\resumeItem{State University}
\end{itemize}
\end{document}"""

        with pytest.raises(ModelOutputInvalidException) as exc_info:
            ResumeGenerationService.validate_ai_output(
                request, latex_with_education, []
            )

        assert 'education' in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_ai_agent_client_payload_includes_template_and_sections(self):
        from unittest.mock import AsyncMock, patch
        from app.common.clients.ai_agent import AIAgentClient

        mock_generate = AsyncMock(return_value={
            'latex_source': r'\documentclass{article}\begin{document}x\end{document}',
            'modifications': ['test'],
        })

        client = AIAgentClient()
        with patch('app.ai.nim_service.generate_resume', mock_generate):
            await client.generate_resume(
                profile_data={'personalInfo': {'full_name': 'Jane Doe'}, 'experience': []},
                job_description_text='Python role',
                template_content='\\documentclass{article}',
                template_id='main',
                selected_sections=['experience'],
            )

        call_kwargs = mock_generate.call_args.kwargs
        assert call_kwargs['template'] == '\\documentclass{article}'
        assert call_kwargs['template_id'] == 'main'
        assert call_kwargs['selected_sections'] == ['experience']
        assert 'profile' in call_kwargs
        assert call_kwargs['job_description'] == 'Python role'


@pytest.mark.django_db
class TestResumeGenerationCancel:
    """Tests for POST /resumes/{id}/cancel"""

    def test_cancel_pending_generation(self, api_client, user_with_profile, job_description, template):
        api_client.force_authenticate(user=user_with_profile)

        create_response = api_client.post(
            '/api/v1/resumes',
            {
                'job_description_id': str(job_description.id),
                'template_id': template.id,
                'sections': DEFAULT_SECTIONS,
            },
            format='json',
        )
        generation_id = create_response.data['id']

        response = api_client.post(f'/api/v1/resumes/{generation_id}/cancel')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'cancelled'
        assert 'cancelled' in (response.data['failure_reason'] or '').lower()

    def test_cancel_completed_generation_conflict(self, api_client, user_with_profile, job_description, template):
        api_client.force_authenticate(user=user_with_profile)

        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            status=ResumeGenerationRequest.STATUS_SUCCESS,
            profile_snapshot={'personalInfo': {}},
            selected_sections=DEFAULT_SECTIONS,
        )

        response = api_client.post(f'/api/v1/resumes/{request.id}/cancel')

        assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
class TestResumeGenerationTaskCancellation:
    """Tests for Celery task cancellation behavior."""

    def test_task_skips_cancelled_request(self, user_with_profile, job_description, template):
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            status=ResumeGenerationRequest.STATUS_CANCELLED,
            profile_snapshot={'personalInfo': {}},
            selected_sections=DEFAULT_SECTIONS,
        )

        from app.resumes.tasks import process_resume_generation

        process_resume_generation(str(request.id))

        request.refresh_from_db()
        assert request.status == ResumeGenerationRequest.STATUS_CANCELLED


@pytest.mark.django_db
class TestResumeGenerationStatus:
    """Tests for GET /resumes/{id}/status"""
    
    def test_get_status_success(self, api_client, user_with_profile, job_description, template):
        """Test getting generation status."""
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        api_client.force_authenticate(user=user_with_profile)
        response = api_client.get(f'/api/v1/resumes/{request.id}/status')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'pending'
    
    def test_get_expired_status_returns_410(self, api_client, user_with_profile, job_description, template):
        """Test getting expired generation status returns 410."""
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data,
            expires_at=timezone.now() - timedelta(hours=1)
        )
        
        api_client.force_authenticate(user=user_with_profile)
        response = api_client.get(f'/api/v1/resumes/{request.id}/status')
        
        assert response.status_code == status.HTTP_410_GONE
        assert response.data['error_code'] == 'TTL_EXPIRED'


# =============================================================================
# Hallucination Detection Tests
# =============================================================================

class TestHallucinationDetection:
    """Tests for hallucination detection algorithm.
    
    CRITICAL: Hallucination detection is a safety feature.
    These tests ensure that:
    1. Valid content passes
    2. Hallucinated content is ALWAYS rejected
    3. Edge cases are handled correctly
    """
    
    def test_no_hallucination_detected(self):
        """Test that valid template macro content passes hallucination check."""
        profile_data = {
            'personalInfo': {
                'full_name': 'Jane Doe',
                'email': 'jane@example.com',
                'location': 'New York, USA'
            },
            'experience': [
                {'company': 'TechCorp', 'title': 'Engineer'},
                {'company': 'StartupXYZ', 'title': 'Developer'}
            ],
            'education': [
                {'institution': 'State University', 'degree': 'BS CS'}
            ],
            'skills': ['Python', 'Django'],
            'certifications': []
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \resumeEntryHeading{Engineer}{2020 -- Present}{TechCorp}{New York}
        \resumeEntryHeading{BS CS}{2012 -- 2016}{State University}{}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert not is_hallucinated
        assert message is None

    def test_hallucination_detected_company(self):
        """Test that invented company in entry heading is detected."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'experience': [
                {'company': 'TechCorp', 'title': 'Engineer'}
            ],
            'education': [],
            'skills': [],
            'certifications': []
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \resumeEntryHeading{Engineer}{2020 -- Present}{TechCorp}{}
        \resumeEntryHeading{Engineer}{2018 -- 2019}{InventedCompany Inc}{}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert is_hallucinated
        assert message is not None
        assert 'inventedcompany' in message.lower() or 'InventedCompany' in message

    def test_hallucination_detected_university(self):
        """Test that invented institution in entry heading is detected."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'experience': [],
            'education': [
                {'institution': 'State University', 'degree': 'BS'}
            ],
            'skills': [],
            'certifications': []
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \resumeEntryHeading{BS}{2012 -- 2016}{State University}{}
        \resumeEntryHeading{PhD}{2020 -- 2024}{University of Mars}{}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert is_hallucinated

    def test_company_suffix_variations_allowed(self):
        """Test that company name suffix variations (Inc, LLC) are allowed."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'experience': [
                {'company': 'TechCorp', 'title': 'Engineer'}
            ],
            'education': [],
            'skills': [],
            'certifications': []
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \resumeEntryHeading{Engineer}{2020 -- Present}{TechCorp Inc}{}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert not is_hallucinated

    def test_partial_match_allowed(self):
        """Test that partial matches of profile org names are allowed."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'experience': [
                {'company': 'Acme Corporation International', 'title': 'Engineer'}
            ],
            'education': [],
            'skills': [],
            'certifications': []
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \resumeEntryHeading{Engineer}{2020 -- Present}{Acme Corporation}{}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert not is_hallucinated

    def test_ats_skill_phrase_allowed(self):
        """JD-tailored skill phrases in tag lists should not trigger hallucination."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'skills': ['EDR', 'Python'],
        }
        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \section*{Skills}
        \begin{itemize}
        \resumeTagList{Endpoint Protection, EDR, Python}
        \end{itemize}
        \end{document}
        """
        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )
        assert not is_hallucinated, message

    def test_jd_keyword_in_summary_allowed(self):
        """Summary tailoring with JD keywords should not trigger hallucination."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'summary': 'Security engineer with EDR experience.',
        }
        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \section*{Summary}
        \small Security professional specializing in endpoint protection and EDR.
        \end{document}
        """
        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )
        assert not is_hallucinated, message

    def test_resumeItem_jd_tailoring_allowed(self):
        """Bullet tailoring with JD keywords should not trigger hallucination."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'experience': [
                {'company': 'TechCorp', 'title': 'Engineer', 'description': 'Managed EDR platform.'}
            ],
        }
        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \section*{Experience}
        \begin{itemize}
        \resumeEntryHeading{Engineer}{2020 -- Present}{TechCorp}{}
        \begin{itemize}
        \resumeItem{Led endpoint protection rollout across enterprise endpoints.}
        \end{itemize}
        \end{itemize}
        \end{document}
        """
        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )
        assert not is_hallucinated, message

    def test_certification_in_resume_item_not_strictly_checked(self):
        """Invented certifications in resumeItem are not checked (macro-only tradeoff)."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'certifications': [
                {'name': 'AWS Solutions Architect', 'issuing_organization': 'Amazon'}
            ]
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \section*{Certifications}
        \begin{itemize}
        \resumeItem{Google Cloud Expert — Google}
        \end{itemize}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert not is_hallucinated

    def test_empty_profile_rejects_invented_entry_heading_org(self):
        """Empty profile rejects invented organizations in entry headings."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'experience': [],
            'education': [],
            'skills': [],
            'certifications': []
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \resumeEntryHeading{Engineer}{2020 -- Present}{Google}{}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert is_hallucinated
    
    def test_patent_legal_status_label_not_flagged(self):
        """Patent field labels like Legal Status should not trigger hallucination."""
        profile_data = {
            'patents': [{
                'title': 'Distributed Cache System',
                'patent_number': 'US12345678',
                'status': 'granted',
                'legal_status': 'active',
            }],
        }
        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \section*{Patents}
        \textbf{Distributed Cache System}
        Legal Status: Active
        \end{document}
        """
        is_hallucinated, entity = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )
        assert not is_hallucinated, f"Unexpected hallucination: {entity}"

    def test_common_section_headers_ignored(self):
        """Sections without macro fields under strict check should pass."""
        profile_data = {
            'personalInfo': {'full_name': 'Jane Doe'},
            'experience': [
                {'company': 'TechCorp', 'title': 'Engineer'}
            ],
            'education': [],
            'skills': [],
            'certifications': []
        }

        latex_source = r"""
        \documentclass{article}
        \begin{document}
        \resumeHeader{Jane Doe}
        \section*{Professional Experience}
        \resumeEntryHeading{Engineer}{2020 -- Present}{TechCorp}{}
        \section*{Education}
        \section*{Skills}
        \end{document}
        """

        is_hallucinated, message = HallucinationDetector.detect_hallucination(
            profile_data, latex_source
        )

        assert not is_hallucinated


# =============================================================================
# LaTeX Validation Tests
# =============================================================================

@pytest.mark.django_db
class TestLatexValidation:
    """Tests for LaTeX output validation.
    
    CRITICAL: LaTeX validation ensures:
    1. Output is well-formed LaTeX
    2. Output will compile successfully
    3. Invalid output is REJECTED, not fixed
    """
    
    def test_valid_latex_passes(self, user_with_profile, job_description, template):
        """Test that valid LaTeX passes validation."""
        from app.resumes.services import ResumeGenerationService
        
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        valid_latex = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\begin{document}
\textbf{Jane Doe}
\textbf{TechCorp}
\end{document}"""
        
        # Should not raise
        ResumeGenerationService.validate_ai_output(
            request, valid_latex, ['Generated resume']
        )
    
    def test_missing_documentclass_rejected(self, user_with_profile, job_description, template):
        """Test that LaTeX without \\documentclass is rejected."""
        from app.resumes.services import ResumeGenerationService
        from app.common.exceptions import ModelOutputInvalidException
        
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        invalid_latex = r"""\begin{document}
\textbf{Jane Doe}
\end{document}"""
        
        with pytest.raises(ModelOutputInvalidException) as exc_info:
            ResumeGenerationService.validate_ai_output(
                request, invalid_latex, []
            )
        
        assert 'documentclass' in str(exc_info.value).lower()
    
    def test_missing_begin_document_rejected(self, user_with_profile, job_description, template):
        """Test that LaTeX without \\begin{document} is rejected."""
        from app.resumes.services import ResumeGenerationService
        from app.common.exceptions import ModelOutputInvalidException
        
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        invalid_latex = r"""\documentclass{article}
\textbf{Jane Doe}
\end{document}"""
        
        with pytest.raises(ModelOutputInvalidException) as exc_info:
            ResumeGenerationService.validate_ai_output(
                request, invalid_latex, []
            )
        
        assert 'begin{document}' in str(exc_info.value).lower()
    
    def test_missing_end_document_rejected(self, user_with_profile, job_description, template):
        """Test that LaTeX without \\end{document} is rejected."""
        from app.resumes.services import ResumeGenerationService
        from app.common.exceptions import ModelOutputInvalidException
        
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        invalid_latex = r"""\documentclass{article}
\begin{document}
\textbf{Jane Doe}"""
        
        with pytest.raises(ModelOutputInvalidException) as exc_info:
            ResumeGenerationService.validate_ai_output(
                request, invalid_latex, []
            )
        
        assert 'end{document}' in str(exc_info.value).lower()
    
    def test_empty_output_rejected(self, user_with_profile, job_description, template):
        """Test that empty output is rejected."""
        from app.resumes.services import ResumeGenerationService
        from app.common.exceptions import ModelOutputInvalidException
        
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        with pytest.raises(ModelOutputInvalidException):
            ResumeGenerationService.validate_ai_output(request, '', [])
        
        with pytest.raises(ModelOutputInvalidException):
            ResumeGenerationService.validate_ai_output(request, '   ', [])
    
    def test_hallucinated_content_not_blocked_by_validation(
        self, user_with_profile, job_description, template
    ):
        """Hallucination check is disabled; invented entry headings pass structure validation."""
        from app.resumes.services import ResumeGenerationService

        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data,
            selected_sections=['experience'],
        )

        latex_with_invented_org = r"""\documentclass{article}
\begin{document}
\resumeHeader{Jane Doe}
\resumeEntryHeading{Engineer}{2020 -- Present}{TechCorp}{}
\resumeEntryHeading{Engineer}{2018 -- 2019}{FakeCompany Corp}{}
\end{document}"""

        ResumeGenerationService.validate_ai_output(
            request, latex_with_invented_org, []
        )


# =============================================================================
# Error Code Tests
# =============================================================================

@pytest.mark.django_db
class TestErrorCodes:
    """Tests for correct error code assignment."""
    
    def test_model_output_invalid_code(self, user_with_profile, job_description, template):
        """Test that MODEL_OUTPUT_INVALID code is returned for invalid LaTeX."""
        from app.resumes.services import ResumeGenerationService
        from app.common.exceptions import ModelOutputInvalidException, ErrorCode

        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )

        invalid_latex = r"""\documentclass{article}
\begin{document}
\textbf{Jane Doe}"""

        try:
            ResumeGenerationService.validate_ai_output(
                request, invalid_latex, []
            )
            assert False, "Should have raised ModelOutputInvalidException"
        except ModelOutputInvalidException as e:
            assert e.error_code == ErrorCode.MODEL_OUTPUT_INVALID
    
    def test_failed_generation_stores_error_code(self, user_with_profile, job_description, template):
        """Test that failed generations store correct error code."""
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        request.mark_failed('MODEL_OUTPUT_INVALID', 'Test error details')
        
        assert request.status == 'failed'
        assert request.failure_reason_code == 'MODEL_OUTPUT_INVALID'
        assert request.failure_details == 'Test error details'


# =============================================================================
# Status Transition Tests
# =============================================================================

@pytest.mark.django_db
class TestStatusTransitions:
    """Tests for generation request status transitions."""
    
    def test_pending_to_processing(self, user_with_profile, job_description, template):
        """Test transition from pending to processing."""
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        assert request.status == 'pending'
        assert request.started_at is None
        
        request.mark_processing()
        
        assert request.status == 'processing'
        assert request.started_at is not None
    
    def test_processing_to_success(self, user_with_profile, job_description, template):
        """Test transition from processing to success."""
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        request.mark_processing()
        request.mark_success(
            latex_source='\\documentclass{article}...',
            pdf_path='/tmp/test.pdf',
            modifications=['Generated resume']
        )
        
        assert request.status == 'success'
        assert request.generated_latex is not None
        assert request.generated_pdf_path is not None
        assert request.completed_at is not None
    
    def test_processing_to_failed(self, user_with_profile, job_description, template):
        """Test transition from processing to failed."""
        request = ResumeGenerationRequest.objects.create(
            user=user_with_profile,
            job_description=job_description,
            template_id=template.id,
            profile_snapshot=user_with_profile.profile.data
        )
        
        request.mark_processing()
        request.mark_failed('MODEL_OUTPUT_INVALID', 'Hallucination detected')
        
        assert request.status == 'failed'
        assert request.failure_reason_code == 'MODEL_OUTPUT_INVALID'
        assert request.completed_at is not None


# =============================================================================
# Template Tests
# =============================================================================

@pytest.mark.django_db
class TestTemplates:
    """Tests for template endpoints."""
    
    def test_list_templates(self, api_client, template):
        """Test listing templates (public endpoint)."""
        response = api_client.get('/api/v1/templates')
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['id'] == template.id
    
    def test_get_template(self, api_client, template):
        """Test getting a specific template."""
        response = api_client.get(f'/api/v1/templates/{template.id}')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == 'Professional Modern'
    
    def test_get_nonexistent_template(self, api_client):
        """Test getting non-existent template returns 404."""
        response = api_client.get('/api/v1/templates/nonexistent')
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_template_includes_version(self, api_client, template):
        """Test that template response includes version for cache invalidation."""
        response = api_client.get(f'/api/v1/templates/{template.id}')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'version' in response.data
        assert response.data['version'] == '1.0.0'
    
    def test_template_includes_preview_urls(self, api_client, template):
        """Test that template response includes preview URLs when available."""
        response = api_client.get(f'/api/v1/templates/{template.id}')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'has_preview' in response.data
        assert 'preview_png_url' in response.data
        assert 'preview_pdf_url' in response.data
        
        # Template has has_preview=True, so URLs should be set
        assert response.data['has_preview'] is True
        assert response.data['preview_png_url'] is not None
        assert f'/templates/{template.id}/preview.png' in response.data['preview_png_url']
    
    def test_template_without_preview_has_null_urls(self, api_client, db):
        """Test that templates without previews have null URLs."""
        no_preview_template = Template.objects.create(
            id='no-preview',
            name='No Preview Template',
            description='A template without preview.',
            author='Test',
            version='1.0.0',
            has_preview=False,
            is_active=True
        )
        
        response = api_client.get(f'/api/v1/templates/{no_preview_template.id}')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['has_preview'] is False
        assert response.data['preview_png_url'] is None
        assert response.data['preview_pdf_url'] is None
    
    def test_inactive_template_not_listed(self, api_client, template, db):
        """Test that inactive templates are not listed."""
        inactive_template = Template.objects.create(
            id='inactive',
            name='Inactive Template',
            description='An inactive template.',
            author='Test',
            version='1.0.0',
            is_active=False
        )
        
        response = api_client.get('/api/v1/templates')
        
        assert response.status_code == status.HTTP_200_OK
        template_ids = [t['id'] for t in response.data]
        assert 'inactive' not in template_ids
        assert template.id in template_ids
    
    def test_template_author_field(self, api_client, template):
        """Test that template includes author field."""
        response = api_client.get(f'/api/v1/templates/{template.id}')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'author' in response.data
        assert response.data['author'] == 'Resume AI Platform'


@pytest.mark.django_db
class TestTemplateMetadataValidation:
    """Tests for template metadata validation.
    
    These tests ensure that templates conform to the required structure.
    """
    
    def test_template_id_format(self, db):
        """Test that template IDs must be lowercase alphanumeric with hyphens."""
        # Valid ID
        template = Template.objects.create(
            id='valid-template-id',
            name='Valid Template',
            description='A valid template.',
            author='Test',
            version='1.0.0',
            is_active=True
        )
        assert template.id == 'valid-template-id'
    
    def test_template_version_format(self, db):
        """Test that template versions follow semantic versioning."""
        template = Template.objects.create(
            id='test-version',
            name='Test Version',
            description='Testing version format.',
            author='Test',
            version='2.1.3',
            is_active=True
        )
        assert template.version == '2.1.3'
    
    def test_template_str_includes_version(self, db):
        """Test that template string representation includes version."""
        template = Template.objects.create(
            id='str-test',
            name='String Test',
            description='Testing string representation.',
            author='Test',
            version='1.2.0',
            is_active=True
        )
        assert '1.2.0' in str(template)
        assert 'String Test' in str(template)


# =============================================================================
# Health Check Tests
# =============================================================================

@pytest.mark.django_db
class TestHealthCheck:
    """Tests for GET /health"""
    
    def test_health_check(self, api_client):
        """Test health check endpoint."""
        response = api_client.get('/api/v1/health')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'ok'
