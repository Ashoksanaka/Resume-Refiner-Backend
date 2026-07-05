"""
Resume services for the Resume AI platform.

Business logic for:
- Job description management
- Resume generation orchestration
- Hallucination detection
- LaTeX compilation
"""

import re
import logging
from typing import Optional, Set
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.common.models import Template
from app.authentication.models import User, IdempotencyKey
from app.profiles.services import ProfileService
from app.common.exceptions import (
    ResourceNotFoundException,
    TTLExpiredException,
    ModelOutputInvalidException,
    LatexCompileException,
)

logger = logging.getLogger(__name__)


ALLOWED_PROFILE_SECTIONS = frozenset({
    'personalInfo',
    'summary',
    'experience',
    'education',
    'skills',
    'certifications',
    'projects',
    'achievements',
    'publications',
    'patents',
    'licenses',
    'trainings',
    'volunteering',
    'organizations',
    'positions',
    'career_breaks',
    'languages',
    'test_scores',
    'areas_of_interest',
    'hobbies',
})


def filter_profile_snapshot(snapshot: dict, sections: list[str]) -> dict:
    """Keep only selected profile sections; personalInfo is always included."""
    allowed = set(sections) | {'personalInfo'}
    return {key: value for key, value in snapshot.items() if key in allowed}


SECTION_HEADING_PATTERNS = {
    'summary': [
        r'\\resumeSectionTitle\{[^}]*PROFESSIONAL SUMMARY',
        r'\\section\*?\{[^}]*Summary',
    ],
    'experience': [
        r'\\resumeSectionTitle\{[^}]*PROFESSIONAL EXPERIENCE',
        r'\\section\*?\{[^}]*Experience',
    ],
    'education': [
        r'\\resumeSectionTitle\{[^}]*EDUCATION',
        r'\\section\*?\{[^}]*Education',
    ],
    'skills': [
        r'\\resumeSectionTitle\{[^}]*TECHNICAL SKILLS',
        r'\\section\*?\{[^}]*Skills',
    ],
    'certifications': [
        r'\\resumeSectionTitle\{[^}]*CERTIFICATIONS',
        r'\\section\*?\{[^}]*Certifications',
    ],
    'projects': [
        r'\\resumeSectionTitle\{[^}]*TECHNICAL PROJECTS',
        r'\\section\*?\{[^}]*Projects',
    ],
    'achievements': [
        r'\\resumeSectionTitle\{[^}]*ACHIEVEMENTS',
        r'\\section\*?\{[^}]*Achievements',
    ],
    'publications': [
        r'\\resumeSectionTitle\{[^}]*PUBLICATIONS',
        r'\\section\*?\{[^}]*Publications',
    ],
    'patents': [
        r'\\resumeSectionTitle\{[^}]*PATENTS',
        r'\\section\*?\{[^}]*Patents',
    ],
    'licenses': [
        r'\\resumeSectionTitle\{[^}]*LICENSES',
        r'\\section\*?\{[^}]*Licenses',
    ],
    'trainings': [
        r'\\resumeSectionTitle\{[^}]*TRAINING',
        r'\\section\*?\{[^}]*Trainings',
    ],
    'volunteering': [
        r'\\resumeSectionTitle\{[^}]*VOLUNTEER',
        r'\\section\*?\{[^}]*Volunteering',
    ],
    'organizations': [
        r'\\resumeSectionTitle\{[^}]*ORGANIZATIONS',
        r'\\section\*?\{[^}]*Organizations',
    ],
    'positions': [
        r'\\resumeSectionTitle\{[^}]*POSITIONS',
        r'\\section\*?\{[^}]*Positions',
    ],
    'career_breaks': [
        r'\\resumeSectionTitle\{[^}]*CAREER BREAK',
        r'\\section\*?\{[^}]*Career Breaks',
    ],
    'languages': [
        r'\\resumeSectionTitle\{[^}]*LANGUAGES',
        r'\\section\*?\{[^}]*Languages',
    ],
    'test_scores': [
        r'\\resumeSectionTitle\{[^}]*TEST SCORES',
        r'\\section\*?\{[^}]*Test Scores',
    ],
    'areas_of_interest': [
        r'\\resumeSectionTitle\{[^}]*AREAS OF INTEREST',
        r'\\section\*?\{[^}]*Areas of Interest',
    ],
    'hobbies': [
        r'\\resumeSectionTitle\{[^}]*HOBBIES',
        r'\\section\*?\{[^}]*Hobbies',
    ],
}


def profile_section_has_data(snapshot: dict, key: str) -> bool:
    """Return True if the profile snapshot has meaningful data for a section key."""
    if key == 'personalInfo':
        info = snapshot.get('personalInfo') or {}
        return bool(
            (info.get('full_name') or '').strip()
            or (info.get('email') or '').strip()
            or (info.get('phone_number') or '').strip()
            or (info.get('location') or '').strip()
            or (info.get('portfolio_url') or '').strip()
        )
    if key == 'summary':
        return bool((snapshot.get('summary') or '').strip())
    if key in ('skills', 'areas_of_interest', 'hobbies'):
        value = snapshot.get(key) or []
        return isinstance(value, list) and len(value) > 0
    value = snapshot.get(key)
    return isinstance(value, list) and len(value) > 0


def validate_sections_have_data(snapshot: dict, sections: list[str]) -> None:
    """Raise InvalidPayloadException if any requested section has no profile data."""
    empty_sections = [
        section
        for section in sections
        if section != 'personalInfo' and not profile_section_has_data(snapshot, section)
    ]
    if empty_sections:
        raise InvalidPayloadException(
            message='One or more selected sections have no profile data.',
            details={'empty_sections': empty_sections},
        )


def validate_latex_section_boundaries(latex_source: str, selected_sections: list[str]) -> None:
    """Fail if LaTeX contains section headings for sections the user did not select."""
    selected = set(selected_sections) | {'personalInfo'}
    for section_key, patterns in SECTION_HEADING_PATTERNS.items():
        if section_key in selected:
            continue
        for pattern in patterns:
            if re.search(pattern, latex_source, re.IGNORECASE):
                raise ModelOutputInvalidException(
                    f"AI output includes '{section_key}' section which was not selected."
                )


class JobDescriptionService:
    """
    Service class for job description operations.
    """
    
    @staticmethod
    def create_job_description(user: User, text: str, role_name: str) -> JobDescription:
        """
        Create a new job description.
        
        Args:
            user: The user creating the JD
            text: The job description text
            role_name: Target role title
        
        Returns:
            Created JobDescription instance
        """
        jd = JobDescription.objects.create(
            user=user,
            role_name=role_name.strip(),
            text=text.strip()
        )
        logger.info("Job description created: %s for user: %s", jd.id, user.id)
        return jd
    
    @staticmethod
    def get_job_description(user: User, jd_id: str) -> JobDescription:
        """
        Get a job description by ID.
        
        Args:
            user: The user requesting the JD
            jd_id: The job description ID
        
        Returns:
            JobDescription instance
        
        Raises:
            ResourceNotFoundException: If JD not found
            TTLExpiredException: If JD has expired
        """
        try:
            jd = JobDescription.objects.get(id=jd_id, user=user)
        except JobDescription.DoesNotExist:
            raise ResourceNotFoundException('Job description not found.')
        
        if jd.is_expired:
            raise TTLExpiredException()
        
        return jd
    
    @staticmethod
    def delete_job_description(user: User, jd_id: str) -> bool:
        """
        Delete a job description.
        
        Args:
            user: The user deleting the JD
            jd_id: The job description ID
        
        Returns:
            True if deleted
        
        Raises:
            ResourceNotFoundException: If JD not found
        """
        try:
            jd = JobDescription.objects.get(id=jd_id, user=user)
            jd.delete()
            logger.info("Job description deleted: %s", jd_id)
            return True
        except JobDescription.DoesNotExist:
            raise ResourceNotFoundException('Job description not found.')


class HallucinationDetector:
    """
    Detects invented proper nouns in AI-generated LaTeX entry headers.

    Validates only ATS template macros (macro-only scope):
    - \\resumeHeader{name}
    - \\resumeEntryHeading{title}{dates}{org}{location}

    Skills, summary, and \\resumeItem bullet text are NOT scanned so JD/ATS
    keyword tailoring (e.g. "endpoint protection") is allowed.

    Tradeoff: invented employers in \\resumeItem bullets are not caught.
    """

    RESUME_HEADER_PATTERN = re.compile(r'\\resumeHeader\{([^}]+)\}')
    RESUME_ENTRY_HEADING_PATTERN = re.compile(
        r'\\resumeEntryHeading\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}'
    )

    COMPANY_SUFFIXES = {'inc', 'inc.', 'llc', 'ltd', 'ltd.', 'corp', 'corp.', 'co', 'co.'}

    IGNORE_WORDS = {
        'present', 'current', 'remote', 'hybrid', 'onsite',
        'full-time', 'part-time', 'contract', 'internship',
    }

    @classmethod
    def _normalize_text(cls, text: str) -> str:
        """Normalize text for comparison - lowercase, strip, remove punctuation."""
        if not text:
            return ''
        normalized = text.lower().strip()
        normalized = re.sub(r'[.,;:!?\'\"()]', '', normalized)
        return normalized

    @classmethod
    def _strip_latex_markup(cls, text: str) -> str:
        """Remove simple LaTeX formatting commands from macro arguments."""
        if not text:
            return ''
        cleaned = text.strip()
        cleaned = re.sub(r'\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?\{([^}]*)\}', r'\1', cleaned)
        cleaned = cleaned.replace('{', '').replace('}', '')
        return cleaned.strip()

    @classmethod
    def _tokenize(cls, text: str) -> Set[str]:
        """Tokenize text into words, filtering short words."""
        if not text:
            return set()
        words = text.split()
        return {w for w in words if len(w) > 2 and w not in cls.IGNORE_WORDS}

    @classmethod
    def _add_entity_variants(cls, entities: set[str], value: str) -> None:
        """Add normalized value and significant tokens to an entity set."""
        if not value or not str(value).strip():
            return
        normalized = cls._normalize_text(str(value))
        if not normalized:
            return
        entities.add(normalized)
        for word in cls._tokenize(normalized):
            entities.add(word)

    @classmethod
    def _add_list_field(cls, entities: set[str], items: list, *fields: str) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            for field in fields:
                value = item.get(field)
                if isinstance(value, list):
                    for nested in value:
                        cls._add_entity_variants(entities, nested)
                else:
                    cls._add_entity_variants(entities, value)

    @classmethod
    def extract_strict_profile_entities(cls, profile_data: dict) -> dict[str, set[str]]:
        """
        Collect structured proper-noun fields only (no description token soup).

        Returns sets keyed by names, titles, and orgs for macro argument matching.
        """
        names: set[str] = set()
        titles: set[str] = set()
        orgs: set[str] = set()

        personal_info = profile_data.get('personalInfo') or {}
        cls._add_entity_variants(names, personal_info.get('full_name', ''))

        cls._add_list_field(titles, profile_data.get('experience', []), 'title')
        cls._add_list_field(orgs, profile_data.get('experience', []), 'company')

        cls._add_list_field(titles, profile_data.get('education', []), 'degree')
        cls._add_list_field(orgs, profile_data.get('education', []), 'institution')

        cls._add_list_field(titles, profile_data.get('projects', []), 'title', 'role')
        cls._add_list_field(titles, profile_data.get('certifications', []), 'name')
        cls._add_list_field(orgs, profile_data.get('certifications', []), 'issuing_organization')

        cls._add_list_field(titles, profile_data.get('patents', []), 'title')
        cls._add_list_field(orgs, profile_data.get('patents', []), 'assignees', 'applicants')

        cls._add_list_field(titles, profile_data.get('publications', []), 'title')
        cls._add_list_field(titles, profile_data.get('licenses', []), 'name')
        cls._add_list_field(orgs, profile_data.get('licenses', []), 'issuing_organization')

        cls._add_list_field(titles, profile_data.get('trainings', []), 'title')
        cls._add_list_field(orgs, profile_data.get('trainings', []), 'provider')

        cls._add_list_field(titles, profile_data.get('volunteering', []), 'role')
        cls._add_list_field(orgs, profile_data.get('volunteering', []), 'organization')

        cls._add_list_field(titles, profile_data.get('organizations', []), 'role')
        cls._add_list_field(orgs, profile_data.get('organizations', []), 'name')

        cls._add_list_field(titles, profile_data.get('positions', []), 'title')
        cls._add_list_field(orgs, profile_data.get('positions', []), 'organization')

        cls._add_list_field(titles, profile_data.get('achievements', []), 'title')

        return {'names': names, 'titles': titles, 'orgs': orgs}

    @classmethod
    def extract_strict_latex_entities(cls, latex_source: str) -> list[tuple[str, str]]:
        """
        Extract proper nouns from ATS template macros only.

        Returns list of (raw_value, source_key) where source_key is one of:
        resumeHeader:name, resumeEntryHeading:title, resumeEntryHeading:org
        """
        latex_no_comments = re.sub(r'%.*$', '', latex_source, flags=re.MULTILINE)
        entities: list[tuple[str, str]] = []

        for match in cls.RESUME_HEADER_PATTERN.finditer(latex_no_comments):
            entities.append((match.group(1), 'resumeHeader:name'))

        for match in cls.RESUME_ENTRY_HEADING_PATTERN.finditer(latex_no_comments):
            title, _dates, org, _location = match.groups()
            if title.strip():
                entities.append((title, 'resumeEntryHeading:title'))
            if org.strip():
                entities.append((org, 'resumeEntryHeading:org'))

        return entities

    @classmethod
    def _is_date_string(cls, text: str) -> bool:
        """Return True if text is primarily a date or date range."""
        if not text:
            return False

        text_lower = text.lower().strip()
        original_text = text.strip()

        if text_lower in ['present', 'current', 'ongoing', 'now']:
            return True

        month_pattern = r'\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b'
        year_pattern = r'\b(19|20)\d{2}\b'
        range_separators = r'[-–—]|--|to|through'

        has_month = bool(re.search(month_pattern, text_lower))
        has_year = bool(re.search(year_pattern, text_lower))
        has_range_sep = bool(re.search(range_separators, original_text.lower()))

        if has_month and has_year and has_range_sep:
            return True

        if has_month and has_year:
            words = text_lower.split()
            significant_words = [
                w for w in words
                if w not in cls.IGNORE_WORDS
                and not re.match(r'^\d+$', w)
                and not re.search(month_pattern, w)
            ]
            if len(significant_words) <= 1:
                return True

        if has_month and ('present' in text_lower or 'current' in text_lower):
            return True

        if re.match(r'^[\d\s\-]+$', text_lower):
            return True

        if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', original_text):
            return True

        if re.match(r'^\d{4}\s*[-–—]+\s*\d{4}', original_text):
            return True

        if re.match(r'^(19|20)\d{2}\s+(19|20)\d{2}$', text_lower):
            return True

        if has_month and has_year and len(text_lower.split()) <= 3:
            return True

        if re.match(r'^(19|20)\d{2}$', text_lower):
            return True

        return False

    @classmethod
    def _is_location_string(cls, text: str) -> bool:
        """Return True if text looks like a location rather than an organization."""
        if not text:
            return False

        text_lower = text.lower().strip()
        location_indicators = [
            r'\b(city|state|country|region|area|location)\b',
            r'\b(usa|united states|us|uk|united kingdom|canada|australia)\b',
        ]

        for pattern in location_indicators:
            if re.search(pattern, text_lower):
                return True

        if re.match(r'^[a-z\s]+,\s*[a-z\s]+$', text_lower) and text == text_lower:
            return True

        return False

    @classmethod
    def _entity_matches(cls, latex_entity: str, profile_entities: Set[str]) -> bool:
        """Check if a LaTeX entity matches any allowed profile entity."""
        if latex_entity in profile_entities:
            return True

        tokens = cls._tokenize(latex_entity)
        if tokens and all(t in profile_entities for t in tokens):
            return True

        for profile_entity in profile_entities:
            if len(profile_entity) < 4:
                continue
            if profile_entity in latex_entity:
                return True
            if len(latex_entity) >= 4 and latex_entity in profile_entity:
                return True

        for suffix in cls.COMPANY_SUFFIXES:
            stripped = latex_entity.rstrip().removesuffix(suffix).strip()
            if stripped and stripped in profile_entities:
                return True

        return False

    @classmethod
    def _source_label(cls, source_key: str) -> str:
        labels = {
            'resumeHeader:name': 'resume header',
            'resumeEntryHeading:title': 'entry heading title',
            'resumeEntryHeading:org': 'entry heading organization',
        }
        return labels.get(source_key, source_key)

    @classmethod
    def detect_hallucination(cls, profile_data: dict, latex_source: str) -> tuple[bool, Optional[str]]:
        """
        Check for invented proper nouns in template macro fields only.

        Returns:
            (False, None) if valid
            (True, message) if an invented name/title/org is found in macro fields
        """
        profile_entities = cls.extract_strict_profile_entities(profile_data)
        latex_entities = cls.extract_strict_latex_entities(latex_source)

        logger.debug(
            "Strict hallucination check: %d macro fields, names=%d titles=%d orgs=%d",
            len(latex_entities),
            len(profile_entities['names']),
            len(profile_entities['titles']),
            len(profile_entities['orgs']),
        )

        for raw_value, source_key in latex_entities:
            display_value = cls._strip_latex_markup(raw_value)
            if not display_value:
                continue

            if cls._is_date_string(display_value) or cls._is_location_string(display_value):
                continue

            normalized = cls._normalize_text(display_value)
            if not normalized or len(normalized) < 2:
                continue

            if source_key == 'resumeHeader:name':
                allowed = profile_entities['names']
                label = 'name'
            elif source_key == 'resumeEntryHeading:title':
                allowed = profile_entities['titles']
                label = 'title'
            else:
                allowed = profile_entities['orgs']
                label = 'organization'

            if cls._entity_matches(normalized, allowed):
                continue

            logger.warning(
                "Hallucination detected in %s: '%s' not found in profile",
                source_key,
                display_value,
            )
            return (
                True,
                f"Invented {label} '{display_value}' in {cls._source_label(source_key)} "
                f"(not in your profile).",
            )

        return (False, None)


class ResumeGenerationService:
    """
    Service class for resume generation operations.
    """
    
    @staticmethod
    def check_idempotency(
        user: User, 
        idempotency_key: str, 
        endpoint: str
    ) -> Optional[dict]:
        """
        Check if a request with this idempotency key has been processed.
        
        Args:
            user: The user making the request
            idempotency_key: The client-provided key
            endpoint: The endpoint being called
        
        Returns:
            Previous response if key exists and is valid, None otherwise
        """
        try:
            existing = IdempotencyKey.objects.get(
                user=user,
                key=idempotency_key,
                endpoint=endpoint
            )
            if existing.is_valid:
                logger.info(
                    "Idempotency key hit: %s for user %s",
                    idempotency_key, user.id
                )
                return {
                    'status': existing.response_status,
                    'body': existing.response_body,
                }
        except IdempotencyKey.DoesNotExist:
            pass
        return None
    
    @staticmethod
    def store_idempotency(
        user: User,
        idempotency_key: str,
        endpoint: str,
        response_status: int,
        response_body: dict
    ) -> None:
        """
        Store an idempotency key with its response.
        
        Args:
            user: The user who made the request
            idempotency_key: The client-provided key
            endpoint: The endpoint called
            response_status: HTTP status code
            response_body: Response data
        """
        ttl_hours = getattr(settings, 'DATA_TTL_HOURS', 24)
        
        IdempotencyKey.objects.update_or_create(
            user=user,
            key=idempotency_key,
            endpoint=endpoint,
            defaults={
                'response_status': response_status,
                'response_body': response_body,
                'expires_at': timezone.now() + timedelta(hours=ttl_hours),
            }
        )
    
    @staticmethod
    def create_generation_request(
        user: User,
        job_description_id: str,
        template_id: str,
        sections: list[str],
        idempotency_key: Optional[str] = None
    ) -> ResumeGenerationRequest:
        """
        Create a new resume generation request.
        
        Args:
            user: The user requesting generation
            job_description_id: UUID of the job description
            template_id: ID of the selected template
            sections: Profile section keys to include
            idempotency_key: Optional idempotency key
        
        Returns:
            Created ResumeGenerationRequest instance
        """
        # Get job description
        jd = JobDescriptionService.get_job_description(user, job_description_id)
        
        # Verify template exists
        if not Template.objects.filter(id=template_id, is_active=True).exists():
            raise ResourceNotFoundException('Template not found.')
        
        # Get profile snapshot and filter to selected sections
        profile_snapshot = ProfileService.get_profile_snapshot(user)
        validate_sections_have_data(profile_snapshot, sections)
        filtered_snapshot = filter_profile_snapshot(profile_snapshot, sections)
        
        # Create request
        request = ResumeGenerationRequest.objects.create(
            user=user,
            job_description=jd,
            template_id=template_id,
            profile_snapshot=filtered_snapshot,
            selected_sections=list(dict.fromkeys(sections)),
            idempotency_key=idempotency_key,
        )
        
        logger.info(
            "Resume generation request created: %s for user: %s",
            request.id, user.id
        )
        
        return request
    
    @staticmethod
    def get_generation_request(
        user: User,
        generation_id: str
    ) -> ResumeGenerationRequest:
        """
        Get a resume generation request by ID.
        
        Args:
            user: The user requesting the generation
            generation_id: UUID of the generation request
        
        Returns:
            ResumeGenerationRequest instance
        
        Raises:
            ResourceNotFoundException: If not found
            TTLExpiredException: If expired
        """
        try:
            request = ResumeGenerationRequest.objects.get(id=generation_id, user=user)
        except ResumeGenerationRequest.DoesNotExist:
            raise ResourceNotFoundException('Resume generation request not found.')
        
        if request.is_expired:
            raise TTLExpiredException()
        
        return request
    
    @staticmethod
    def list_generation_requests(user: User) -> list:
        """
        List all non-expired generation requests for a user.
        
        Args:
            user: The user whose requests to list
        
        Returns:
            QuerySet of ResumeGenerationRequest instances
        """
        return ResumeGenerationRequest.objects.filter(
            user=user,
            expires_at__gt=timezone.now()
        ).order_by('-created_at')
    
    @staticmethod
    def cancel_generation_request(user: User, generation_id: str) -> ResumeGenerationRequest:
        """
        Cancel an in-progress resume generation request.
        """
        from celery import current_app
        from app.common.exceptions import ConflictException

        generation_request = ResumeGenerationService.get_generation_request(user, generation_id)

        if generation_request.status not in (
            ResumeGenerationRequest.STATUS_PENDING,
            ResumeGenerationRequest.STATUS_PROCESSING,
        ):
            raise ConflictException(
                message='This generation cannot be cancelled because it has already finished.'
            )

        if generation_request.celery_task_id:
            current_app.control.revoke(
                generation_request.celery_task_id,
                terminate=True,
            )

        generation_request.mark_cancelled()
        logger.info("Resume generation cancelled: %s for user: %s", generation_id, user.id)
        return generation_request
    
    @staticmethod
    def validate_ai_output(
        generation_request: ResumeGenerationRequest,
        latex_source: str,
        modifications: list
    ) -> None:
        """
        Validate AI output for LaTeX structure and selected section boundaries.

        Hallucination detection is disabled to allow ATS tailoring (reworded
        titles, skills, and JD keywords). The agent prompt still instructs the
        model not to invent employers or credentials.
        """
        # Check for empty output
        if not latex_source or not latex_source.strip():
            raise ModelOutputInvalidException('AI produced empty output.')
        
        latex_stripped = latex_source.strip()
        
        # Validate LaTeX structure: must start with \documentclass
        if not latex_stripped.startswith('\\documentclass'):
            raise ModelOutputInvalidException(
                'AI output is not valid LaTeX (must start with \\documentclass).'
            )
        
        # Validate LaTeX structure: must have \begin{document}
        if '\\begin{document}' not in latex_source:
            raise ModelOutputInvalidException(
                'AI output is not valid LaTeX (missing \\begin{document}).'
            )
        
        # Validate LaTeX structure: must have \end{document}
        if '\\end{document}' not in latex_source:
            raise ModelOutputInvalidException(
                'AI output is not valid LaTeX (missing \\end{document}).'
            )

        validate_latex_section_boundaries(
            latex_source,
            generation_request.selected_sections or [],
        )

        logger.info(
            "AI output validated for generation request: %s",
            generation_request.id
        )
    
    @staticmethod
    def mark_generation_failed(
        generation_request: ResumeGenerationRequest,
        error_code: str,
        error_details: str
    ) -> None:
        """
        Mark a generation request as failed.
        
        Args:
            generation_request: The request to mark as failed
            error_code: Machine-readable error code
            error_details: Human-readable details
        """
        generation_request.mark_failed(error_code, error_details)
        logger.error(
            "Generation request failed: %s, code: %s",
            generation_request.id, error_code
        )
