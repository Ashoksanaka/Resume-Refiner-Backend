"""
Serializers for profile endpoints.

As per API contract:
- GET /profiles/me: returns Profile schema
- PUT /profiles/me: full profile update
- PATCH /profiles/me: partial profile update

Profile data is validated against /backend/schemas/profile.json
"""

import json
import logging
import re
import uuid
from pathlib import Path
from rest_framework import serializers
from jsonschema import validate, ValidationError as JSONSchemaValidationError
from django.conf import settings
from app.profiles.models import Profile, ProfileSaveEvent

logger = logging.getLogger(__name__)

PHONE_NUMBER_PATTERN = re.compile(r'^\+\d{1,4}-\d{6,14}$')
LANGUAGE_PROFICIENCY_CHOICES = ('basic', 'conversational', 'professional', 'native')
LEGACY_LANGUAGE_PROFICIENCY_CHOICES = (
    'native', 'full_professional', 'limited_professional', 'conversational', 'basic'
)


def validate_date_range(attrs, start_key='start_date', end_key='end_date', *, skip_future_end=False):
    """Validate start/end dates: not in future; end after start when end is not null."""
    from datetime import date
    today = date.today()

    start_date = attrs.get(start_key)
    end_date = attrs.get(end_key)

    if start_date and start_date > today:
        raise serializers.ValidationError({
            start_key: 'Start date cannot be in the future.'
        })

    if end_date is not None:
        if not skip_future_end and end_date > today:
            raise serializers.ValidationError({
                end_key: 'End date cannot be in the future.'
            })

        if start_date and end_date < start_date:
            raise serializers.ValidationError({
                end_key: 'End date must be after start date.'
            })

    return attrs


def validate_not_future_date(attrs, date_key, label=None):
    """Validate a single date field is not in the future."""
    from datetime import date
    today = date.today()

    value = attrs.get(date_key)
    if value and value > today:
        field_label = label or date_key.replace('_', ' ')
        raise serializers.ValidationError({
            date_key: f'{field_label.capitalize()} cannot be in the future.'
        })

    return attrs


def get_profile_schema():
    """
    Load the profile JSON schema from file.
    Cached for performance.
    """
    schema_path = Path(settings.BASE_DIR) / 'schemas' / 'profile.json'
    with open(schema_path, 'r') as f:
        return json.load(f)


# Cache the schema at module load time
PROFILE_SCHEMA = None


def validate_profile_data(data: dict) -> None:
    """
    Validate profile data against the JSON schema.
    
    Raises:
        serializers.ValidationError: If validation fails
    """
    global PROFILE_SCHEMA
    if PROFILE_SCHEMA is None:
        PROFILE_SCHEMA = get_profile_schema()
    
    try:
        validate(instance=data, schema=PROFILE_SCHEMA)
    except JSONSchemaValidationError as e:
        # Extract meaningful error message
        path = '.'.join(str(p) for p in e.absolute_path) if e.absolute_path else 'root'
        raise serializers.ValidationError({
            path: [e.message]
        })


class PersonalInfoSerializer(serializers.Serializer):
    """Serializer for personalInfo section."""
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField(max_length=255)
    phone_number = serializers.CharField(max_length=50)
    location = serializers.CharField(max_length=255)
    portfolio_url = serializers.URLField(max_length=512, required=False, allow_blank=True)

    def validate_email(self, value):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if value.lower() != request.user.email.lower():
                raise serializers.ValidationError('Email cannot be changed.')
        return value.lower()

    def validate_phone_number(self, value):
        if not PHONE_NUMBER_PATTERN.match(value):
            raise serializers.ValidationError(
                'Phone number must use format +<countryCode>-<number> (e.g. +91-9876543210).'
            )
        return value


class ExperienceSerializer(serializers.Serializer):
    """Serializer for experience items with date validation."""
    company = serializers.CharField(max_length=255)
    title = serializers.CharField(max_length=255)
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=5000, required=True, allow_blank=False)
    
    def validate(self, attrs):
        """Validate dates: not in future, end_date after start_date when present."""
        from datetime import date
        today = date.today()
        
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        
        # Prevent future dates (non-negotiable per product requirements)
        if start_date and start_date > today:
            raise serializers.ValidationError({
                'start_date': 'Start date cannot be in the future.'
            })
        
        if end_date is not None:
            if end_date > today:
                raise serializers.ValidationError({
                    'end_date': 'End date cannot be in the future.'
                })
            
            if start_date and end_date < start_date:
                raise serializers.ValidationError({
                    'end_date': 'End date must be after start date.'
                })
        
        return attrs


class EducationSerializer(serializers.Serializer):
    """Serializer for education items with date and grade validation."""
    DEGREE_LEVELS = (
        "Bachelor's",
        "Master's",
        "Doctorate",
        "Diploma",
        "Associate",
        "High School",
        "Other",
    )
    COURSES = (
        "BTech", "BE", "MTech", "ME", "BSc", "MSc", "MBA", "BCA", "MCA",
        "BCom", "MCom", "BA", "MA", "PhD", "Other",
    )

    institution = serializers.CharField(max_length=255)
    degree = serializers.CharField(max_length=255, required=False, allow_blank=True)
    degree_level = serializers.ChoiceField(choices=DEGREE_LEVELS)
    degree_level_other = serializers.CharField(max_length=255, required=False, allow_blank=True)
    course = serializers.ChoiceField(choices=COURSES)
    course_other = serializers.CharField(max_length=255, required=False, allow_blank=True)
    specialization = serializers.CharField(max_length=255)
    location = serializers.CharField(max_length=255)
    grade_type = serializers.ChoiceField(choices=('percentage', 'cgpa'))
    grade_value = serializers.FloatField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    def validate(self, attrs):
        """Validate dates, grades, and Other enum fields."""
        from datetime import date
        today = date.today()

        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')

        if start_date and start_date > today:
            raise serializers.ValidationError({
                'start_date': 'Start date cannot be in the future.'
            })

        if end_date is not None:
            if end_date > today:
                raise serializers.ValidationError({
                    'end_date': 'End date cannot be in the future.'
                })

            if start_date and end_date < start_date:
                raise serializers.ValidationError({
                    'end_date': 'End date must be after start date.'
                })

        if attrs.get('degree_level') == 'Other' and not attrs.get('degree_level_other', '').strip():
            raise serializers.ValidationError({
                'degree_level_other': 'Please specify the degree level.'
            })

        if attrs.get('course') == 'Other' and not attrs.get('course_other', '').strip():
            raise serializers.ValidationError({
                'course_other': 'Please specify the course.'
            })

        grade_type = attrs.get('grade_type')
        grade_value = attrs.get('grade_value')

        if grade_value is None:
            raise serializers.ValidationError({
                'grade_value': 'Grade value is required.'
            })

        if grade_type == 'percentage':
            if grade_value < 0 or grade_value > 100:
                raise serializers.ValidationError({
                    'grade_value': 'Percentage must be between 0 and 100.'
                })
        elif grade_type == 'cgpa':
            if grade_value < 0 or grade_value > 10:
                raise serializers.ValidationError({
                    'grade_value': 'CGPA must be between 0 and 10.'
                })

        return attrs


class CertificationSerializer(serializers.Serializer):
    """Serializer for certification items."""
    name = serializers.CharField(max_length=255)
    issuing_organization = serializers.CharField(max_length=255)
    issue_date = serializers.DateField(required=False)


class ProjectSerializer(serializers.Serializer):
    """Serializer for project items with date validation."""
    id = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    role = serializers.CharField(max_length=150)
    description = serializers.CharField(max_length=5000, required=True, allow_blank=False)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    ongoing = serializers.BooleanField()
    technologies = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True
    )
    link = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    github_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    deployment_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    achievements = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        allow_empty=True
    )
    
    def validate(self, attrs):
        """Validate dates: not in future unless ongoing, end_date after start_date."""
        from datetime import date
        today = date.today()
        
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        ongoing = attrs.get('ongoing', False)
        
        if start_date and not ongoing and start_date > today:
            raise serializers.ValidationError({
                'start_date': 'Start date cannot be in the future for completed projects.'
            })
        
        if end_date is not None and not ongoing and end_date > today:
            raise serializers.ValidationError({
                'end_date': 'End date cannot be in the future.'
            })
        
        if start_date and end_date is not None and end_date < start_date:
            raise serializers.ValidationError({
                'end_date': 'End date must be after start date.'
            })
        
        return attrs


class AchievementSerializer(serializers.Serializer):
    """Serializer for achievement items."""
    id = serializers.UUIDField()
    title = serializers.CharField(max_length=250)
    description = serializers.CharField(max_length=2000, required=True, allow_blank=False)
    issuer = serializers.CharField(max_length=255, required=False, allow_blank=True)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    is_virtual = serializers.BooleanField(required=False)
    date = serializers.DateField(required=False, allow_null=True)
    
    def validate(self, attrs):
        validate_not_future_date(attrs, 'date', 'date')
        return attrs


class AddressSerializer(serializers.Serializer):
    """Serializer for address object."""
    street = serializers.CharField(max_length=250, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    region = serializers.CharField(max_length=100, required=False, allow_blank=True)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    geolocation = serializers.DictField(required=False, allow_null=True)


class GeolocationSerializer(serializers.Serializer):
    """Serializer for geolocation object."""
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class SocialUrlsSerializer(serializers.Serializer):
    """Serializer for social URLs object."""
    linkedin = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    github = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    twitter = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    portfolio = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    website = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    other = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True
    )


class ProfilePictureSerializer(serializers.Serializer):
    """Serializer for profile picture object."""
    url = serializers.CharField()
    thumbnail_url = serializers.CharField()
    uploaded_at = serializers.DateTimeField()


class VolunteeringSerializer(serializers.Serializer):
    """Serializer for volunteering items with date validation."""
    id = serializers.UUIDField()
    organization = serializers.CharField(max_length=255)
    role = serializers.CharField(max_length=255)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=5000, required=True, allow_blank=False)
    
    def validate(self, attrs):
        return validate_date_range(attrs)


class PositionSerializer(serializers.Serializer):
    """Serializer for position items with date validation."""
    id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    organization = serializers.CharField(max_length=255)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=5000, required=True, allow_blank=False)
    
    def validate(self, attrs):
        return validate_date_range(attrs)


class CareerBreakSerializer(serializers.Serializer):
    """Serializer for career break items with date validation."""
    id = serializers.UUIDField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    reason = serializers.ChoiceField(choices=['parental', 'health', 'travel', 'education', 'other'])
    description = serializers.CharField(max_length=2000, required=True, allow_blank=False)
    
    def validate(self, attrs):
        return validate_date_range(attrs)


class LicenseSerializer(serializers.Serializer):
    """Serializer for license items."""
    id = serializers.UUIDField()
    name = serializers.CharField(max_length=255)
    issuer = serializers.CharField(max_length=255)
    license_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    awarded_date = serializers.DateField(required=False, allow_null=True)
    expiration_date = serializers.DateField(required=False, allow_null=True)
    date = serializers.DateField(required=False, allow_null=True)
    url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    
    def validate(self, attrs):
        from datetime import date
        today = date.today()

        for field in ('date', 'awarded_date'):
            value = attrs.get(field)
            if value and value > today:
                raise serializers.ValidationError({
                    field: f'{field.replace("_", " ").capitalize()} cannot be in the future.'
                })

        awarded_date = attrs.get('awarded_date') or attrs.get('date')
        expiration_date = attrs.get('expiration_date')
        if awarded_date and expiration_date is not None and expiration_date < awarded_date:
            raise serializers.ValidationError({
                'expiration_date': 'Expiration date must be after awarded date.'
            })

        return attrs


class TrainingSerializer(serializers.Serializer):
    """Serializer for training items."""
    id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    provider = serializers.CharField(max_length=255)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    venue = serializers.CharField(max_length=255, required=False, allow_blank=True)
    is_virtual = serializers.BooleanField(required=False)
    date = serializers.DateField(required=False, allow_null=True)
    certificate_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    description = serializers.CharField(max_length=2000, required=True, allow_blank=False)
    
    def validate(self, attrs):
        validate_not_future_date(attrs, 'date', 'date')
        return validate_date_range(attrs)


class PublicationAuthorSerializer(serializers.Serializer):
    """Serializer for publication author entries."""
    name = serializers.CharField(max_length=255)
    affiliation = serializers.CharField(max_length=255, required=False, allow_blank=True)
    order = serializers.IntegerField(required=False, min_value=1)
    is_corresponding = serializers.BooleanField(required=False)
    orcid = serializers.CharField(max_length=50, required=False, allow_blank=True)


class PublicationSerializer(serializers.Serializer):
    """Serializer for publication items."""
    id = serializers.UUIDField()
    title = serializers.CharField(max_length=500)
    subtitle = serializers.CharField(max_length=500, required=False, allow_blank=True)
    authors = PublicationAuthorSerializer(many=True, min_length=1)
    doi = serializers.CharField(max_length=255, required=False, allow_blank=True)
    pmid = serializers.CharField(max_length=50, required=False, allow_blank=True)
    pmcid = serializers.CharField(max_length=50, required=False, allow_blank=True)
    isbn = serializers.CharField(max_length=50, required=False, allow_blank=True)
    issn = serializers.CharField(max_length=50, required=False, allow_blank=True)
    arxiv_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    editor = serializers.CharField(max_length=255, required=False, allow_blank=True)
    venue = serializers.CharField(max_length=255, required=False, allow_blank=True)
    volume = serializers.CharField(max_length=50, required=False, allow_blank=True)
    issue = serializers.CharField(max_length=50, required=False, allow_blank=True)
    page_range = serializers.CharField(max_length=100, required=False, allow_blank=True)
    article_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    date = serializers.DateField(required=False, allow_null=True)
    online_date = serializers.DateField(required=False, allow_null=True)
    accepted_date = serializers.DateField(required=False, allow_null=True)
    publication_year = serializers.IntegerField(required=False, min_value=1000, max_value=9999)
    publication_month = serializers.IntegerField(required=False, min_value=1, max_value=12)
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True
    )
    subject_categories = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True
    )
    url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    landing_page_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    pdf_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    repository_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    version_label = serializers.CharField(max_length=50, required=False, allow_blank=True)
    version_date = serializers.DateField(required=False, allow_null=True)
    funding_sources = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        allow_empty=True
    )
    grant_numbers = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True
    )
    trial_registry = serializers.CharField(max_length=255, required=False, allow_blank=True)
    ethics_approvals = serializers.CharField(max_length=255, required=False, allow_blank=True)
    copyright_holder = serializers.CharField(max_length=255, required=False, allow_blank=True)
    license = serializers.CharField(max_length=255, required=False, allow_blank=True)
    reuse_permissions = serializers.CharField(max_length=500, required=False, allow_blank=True)
    citation_count = serializers.IntegerField(required=False, min_value=0)
    altmetric_score = serializers.FloatField(required=False, min_value=0)
    language = serializers.CharField(max_length=100, required=False, allow_blank=True)
    publication_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    document_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    abstract = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    
    def validate(self, attrs):
        from datetime import date
        today = date.today()

        for field in ('date', 'online_date', 'accepted_date', 'version_date'):
            value = attrs.get(field)
            if value and value > today:
                raise serializers.ValidationError({
                    field: f'{field.replace("_", " ").capitalize()} cannot be in the future.'
                })

        if attrs.get('accepted_date') and attrs.get('date'):
            if attrs['date'] < attrs['accepted_date']:
                raise serializers.ValidationError({
                    'date': 'Publication date must be on or after accepted date.'
                })

        if attrs.get('online_date') and attrs.get('date'):
            if attrs['online_date'] > attrs['date']:
                raise serializers.ValidationError({
                    'online_date': 'Online date cannot be after publication date.'
                })

        return attrs


class PatentSerializer(serializers.Serializer):
    """Serializer for patent items."""
    id = serializers.UUIDField()
    title = serializers.CharField(max_length=500)
    patent_number = serializers.CharField(max_length=100)
    status = serializers.ChoiceField(choices=['filed', 'granted', 'pending'])
    abstract = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True
    )
    application_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    publication_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    inventors = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        allow_empty=True
    )
    applicants = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        allow_empty=True
    )
    assignees = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        allow_empty=True
    )
    filing_date = serializers.DateField(required=False, allow_null=True)
    priority_date = serializers.DateField(required=False, allow_null=True)
    publication_date = serializers.DateField(required=False, allow_null=True)
    grant_date = serializers.DateField(required=False, allow_null=True)
    patent_office = serializers.CharField(max_length=255, required=False, allow_blank=True)
    family_id = serializers.CharField(max_length=100, required=False, allow_blank=True)
    ipc_codes = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_empty=True
    )
    cpc_codes = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_empty=True
    )
    us_classifications = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_empty=True
    )
    kind_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    legal_status = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pct_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    representative = serializers.CharField(max_length=255, required=False, allow_blank=True)
    url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    drawings_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    pdf_url = serializers.URLField(max_length=512, required=False, allow_null=True, allow_blank=True)
    forward_citations = serializers.IntegerField(required=False, min_value=0)
    family_size = serializers.IntegerField(required=False, min_value=0)
    publication_languages = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True
    )
    
    def validate(self, attrs):
        from datetime import date
        today = date.today()

        for field in ('filing_date', 'priority_date', 'publication_date', 'grant_date'):
            value = attrs.get(field)
            if value and value > today:
                raise serializers.ValidationError({
                    field: f'{field.replace("_", " ").capitalize()} cannot be in the future.'
                })

        filing_date = attrs.get('filing_date')
        priority_date = attrs.get('priority_date')
        publication_date = attrs.get('publication_date')
        grant_date = attrs.get('grant_date')

        if priority_date and filing_date and priority_date > filing_date:
            raise serializers.ValidationError({
                'priority_date': 'Priority date cannot be after filing date.'
            })

        if filing_date and publication_date and publication_date < filing_date:
            raise serializers.ValidationError({
                'publication_date': 'Publication date must be on or after filing date.'
            })

        if filing_date and grant_date and grant_date < filing_date:
            raise serializers.ValidationError({
                'grant_date': 'Grant date must be on or after filing date.'
            })

        return attrs


class HonorAwardSerializer(serializers.Serializer):
    """Serializer for honor/award items."""
    id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    issuer = serializers.CharField(max_length=255)
    date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    
    def validate(self, attrs):
        """Validate date not in future."""
        from datetime import date
        today = date.today()
        
        award_date = attrs.get('date')
        if award_date and award_date > today:
            raise serializers.ValidationError({
                'date': 'Date cannot be in the future.'
            })
        
        return attrs


class TestScoreSerializer(serializers.Serializer):
    """Serializer for test score items."""
    id = serializers.UUIDField()
    test_name = serializers.CharField(max_length=255)
    score = serializers.CharField(max_length=50)  # Can be number or string
    max_score = serializers.FloatField(required=False, allow_null=True)
    percentile = serializers.FloatField(required=False, allow_null=True)
    date = serializers.DateField(required=False, allow_null=True)
    
    def validate(self, attrs):
        """Validate date not in future."""
        from datetime import date
        today = date.today()
        
        test_date = attrs.get('date')
        if test_date and test_date > today:
            raise serializers.ValidationError({
                'date': 'Date cannot be in the future.'
            })
        
        return attrs


class LanguageSerializer(serializers.Serializer):
    """Serializer for language items."""
    language = serializers.CharField(max_length=100)
    read_proficiency = serializers.ChoiceField(choices=LANGUAGE_PROFICIENCY_CHOICES)
    write_proficiency = serializers.ChoiceField(choices=LANGUAGE_PROFICIENCY_CHOICES)
    speak_proficiency = serializers.ChoiceField(choices=LANGUAGE_PROFICIENCY_CHOICES)
    proficiency = serializers.ChoiceField(
        choices=LEGACY_LANGUAGE_PROFICIENCY_CHOICES,
        required=False
    )
    certification = serializers.CharField(max_length=255, required=False, allow_blank=True)


class OrganizationSerializer(serializers.Serializer):
    """Serializer for organization items with date validation."""
    id = serializers.UUIDField()
    name = serializers.CharField(max_length=255)
    role = serializers.CharField(max_length=255)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=2000, required=True, allow_blank=False)
    
    def validate(self, attrs):
        return validate_date_range(attrs)


class ContactInfoSerializer(serializers.Serializer):
    """Serializer for contact info object (sensitive)."""
    primary_phone = serializers.CharField(max_length=50)
    secondary_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    secondary_email = serializers.EmailField(max_length=255, required=False, allow_blank=True)
    preferred_contact_method = serializers.ChoiceField(
        choices=['email', 'phone', 'none'],
        required=False
    )
    timezone = serializers.CharField(max_length=100, required=False, allow_blank=True)


class ProfileDataSerializer(serializers.Serializer):
    """
    Serializer for the profile data structure.
    
    This represents the inner data field of the Profile model,
    which matches the JSON schema at /backend/schemas/profile.json.
    
    SECURITY: Array lengths are limited to prevent DoS attacks.
    """
    
    personalInfo = PersonalInfoSerializer()
    summary = serializers.CharField(max_length=2500, required=False, allow_blank=True)
    experience = ExperienceSerializer(many=True, required=False, max_length=25)  # Max 25 jobs
    education = EducationSerializer(many=True, required=False, max_length=10)    # Max 10 degrees
    skills = serializers.ListField(
        child=serializers.CharField(max_length=100),
        allow_empty=True,
        required=False,
        max_length=50  # Max 50 skills
    )
    certifications = CertificationSerializer(many=True, required=False, default=list, max_length=20)  # Max 20 certs
    projects = ProjectSerializer(many=True, required=False, max_length=50)
    achievements = AchievementSerializer(many=True, required=False, max_length=50)
    areas_of_interest = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        max_length=50
    )
    hobbies = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        max_length=50
    )
    address = AddressSerializer(required=False, allow_null=True)
    social_urls = SocialUrlsSerializer(required=False, allow_null=True)
    profile_picture = ProfilePictureSerializer(required=False, allow_null=True)
    volunteering = VolunteeringSerializer(many=True, required=False, max_length=50)
    positions = PositionSerializer(many=True, required=False, max_length=50)
    career_breaks = CareerBreakSerializer(many=True, required=False, max_length=20)
    licenses = LicenseSerializer(many=True, required=False, max_length=50)
    trainings = TrainingSerializer(many=True, required=False, max_length=50)
    publications = PublicationSerializer(many=True, required=False, max_length=50)
    patents = PatentSerializer(many=True, required=False, max_length=50)
    honors_awards = HonorAwardSerializer(many=True, required=False, max_length=50)
    test_scores = TestScoreSerializer(many=True, required=False, max_length=50)
    languages = LanguageSerializer(many=True, required=False, max_length=50)
    organizations = OrganizationSerializer(many=True, required=False, max_length=50)
    contact_info = ContactInfoSerializer(required=False, allow_null=True)
    
    def validate(self, attrs):
        """
        Additional validation against JSON schema.
        Convert date objects to strings for JSON schema validation.
        """
        # Convert to dict with date strings for schema validation
        data_for_validation = self._serialize_dates(attrs)
        validate_profile_data(data_for_validation)
        return attrs
    
    def _serialize_dates(self, data):
        """Convert date objects to ISO format strings for JSON schema validation."""
        result = {}
        date_array_fields = (
            'experience', 'education', 'certifications', 'projects', 'achievements',
            'volunteering', 'positions', 'career_breaks', 'licenses', 'trainings',
            'publications', 'patents', 'honors_awards', 'test_scores', 'organizations'
        )
        for key, value in data.items():
            if key in date_array_fields:
                result[key] = [
                    {
                        k: v.isoformat() if hasattr(v, 'isoformat') else v
                        for k, v in item.items()
                    }
                    for item in (value or [])
                ]
            elif key == 'profile_picture' and value:
                result[key] = {
                    k: v.isoformat() if hasattr(v, 'isoformat') else v
                    for k, v in value.items()
                }
            elif isinstance(value, dict):
                result[key] = self._serialize_dates(value)
            else:
                result[key] = value
        return result


class ProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for the Profile model.
    
    The profile data structure is stored in the 'data' JSONField
    and is represented directly in API responses (not nested under 'data').
    
    SECURITY: contact_info is redacted for non-owners in views.
    """
    
    # Flatten the data field to the top level
    personalInfo = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    experience = serializers.SerializerMethodField()
    education = serializers.SerializerMethodField()
    skills = serializers.SerializerMethodField()
    certifications = serializers.SerializerMethodField()
    projects = serializers.SerializerMethodField()
    achievements = serializers.SerializerMethodField()
    areas_of_interest = serializers.SerializerMethodField()
    hobbies = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    social_urls = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    volunteering = serializers.SerializerMethodField()
    positions = serializers.SerializerMethodField()
    career_breaks = serializers.SerializerMethodField()
    licenses = serializers.SerializerMethodField()
    trainings = serializers.SerializerMethodField()
    publications = serializers.SerializerMethodField()
    patents = serializers.SerializerMethodField()
    honors_awards = serializers.SerializerMethodField()
    test_scores = serializers.SerializerMethodField()
    languages = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()
    contact_info = serializers.SerializerMethodField()
    
    class Meta:
        model = Profile
        fields = [
            'personalInfo', 'summary', 'experience', 'education', 'skills',
            'certifications', 'projects', 'achievements', 'areas_of_interest',
            'hobbies', 'address', 'social_urls', 'profile_picture',
            'volunteering', 'positions', 'career_breaks', 'licenses',
            'trainings', 'publications', 'patents', 'honors_awards',
            'test_scores', 'languages', 'organizations', 'contact_info'
        ]
    
    def get_personalInfo(self, obj):
        return obj.data.get('personalInfo', {})
    
    def get_summary(self, obj):
        return obj.data.get('summary', '')
    
    def get_experience(self, obj):
        return obj.data.get('experience', [])
    
    def get_education(self, obj):
        return obj.data.get('education', [])
    
    def get_skills(self, obj):
        return obj.data.get('skills', [])
    
    def get_certifications(self, obj):
        return obj.data.get('certifications', [])
    
    def get_projects(self, obj):
        return obj.data.get('projects', [])
    
    def get_achievements(self, obj):
        return obj.data.get('achievements', [])
    
    def get_areas_of_interest(self, obj):
        return obj.data.get('areas_of_interest', [])
    
    def get_hobbies(self, obj):
        return obj.data.get('hobbies', [])
    
    def get_address(self, obj):
        return obj.data.get('address')
    
    def get_social_urls(self, obj):
        return obj.data.get('social_urls')
    
    def get_profile_picture(self, obj):
        return obj.data.get('profile_picture')
    
    def get_volunteering(self, obj):
        return obj.data.get('volunteering', [])
    
    def get_positions(self, obj):
        return obj.data.get('positions', [])
    
    def get_career_breaks(self, obj):
        return obj.data.get('career_breaks', [])
    
    def get_licenses(self, obj):
        return obj.data.get('licenses', [])
    
    def get_trainings(self, obj):
        return obj.data.get('trainings', [])
    
    def get_publications(self, obj):
        return obj.data.get('publications', [])
    
    def get_patents(self, obj):
        return obj.data.get('patents', [])
    
    def get_honors_awards(self, obj):
        return obj.data.get('honors_awards', [])
    
    def get_test_scores(self, obj):
        return obj.data.get('test_scores', [])
    
    def get_languages(self, obj):
        return obj.data.get('languages', [])
    
    def get_organizations(self, obj):
        return obj.data.get('organizations', [])
    
    def get_contact_info(self, obj):
        # Redaction handled in views
        return obj.data.get('contact_info')
    
    def _convert_uuids_to_strings(self, data):
        """Recursively convert UUID objects to strings for JSON serialization."""
        if isinstance(data, uuid.UUID):
            return str(data)
        elif isinstance(data, dict):
            return {k: self._convert_uuids_to_strings(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_uuids_to_strings(item) for item in data]
        else:
            return data
    
    def to_representation(self, instance):
        """Override to convert UUIDs to strings before serialization."""
        data = super().to_representation(instance)
        return self._convert_uuids_to_strings(data)


class ProfileCreateUpdateSerializer(serializers.Serializer):
    """
    Serializer for creating/updating profiles.
    
    Handles both PUT (full replacement) and PATCH (partial update).
    
    SECURITY: Array lengths are limited to prevent DoS attacks.
    """
    
    personalInfo = PersonalInfoSerializer(required=False)
    summary = serializers.CharField(max_length=2500, min_length=10, required=True, allow_blank=False)
    experience = ExperienceSerializer(many=True, required=False, max_length=25)  # Max 25 jobs
    education = EducationSerializer(many=True, required=False, max_length=10)    # Max 10 degrees
    skills = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        max_length=50  # Max 50 skills
    )
    certifications = CertificationSerializer(many=True, required=False, max_length=20)  # Max 20 certs
    projects = ProjectSerializer(many=True, required=False, max_length=50)
    achievements = AchievementSerializer(many=True, required=False, max_length=50)
    areas_of_interest = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        max_length=50
    )
    hobbies = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        max_length=50
    )
    address = AddressSerializer(required=False, allow_null=True)
    social_urls = SocialUrlsSerializer(required=False, allow_null=True)
    profile_picture = ProfilePictureSerializer(required=False, allow_null=True)
    volunteering = VolunteeringSerializer(many=True, required=False, max_length=50)
    positions = PositionSerializer(many=True, required=False, max_length=50)
    career_breaks = CareerBreakSerializer(many=True, required=False, max_length=20)
    licenses = LicenseSerializer(many=True, required=False, max_length=50)
    trainings = TrainingSerializer(many=True, required=False, max_length=50)
    publications = PublicationSerializer(many=True, required=False, max_length=50)
    patents = PatentSerializer(many=True, required=False, max_length=50)
    honors_awards = HonorAwardSerializer(many=True, required=False, max_length=50)
    test_scores = TestScoreSerializer(many=True, required=False, max_length=50)
    languages = LanguageSerializer(many=True, required=False, max_length=50)
    organizations = OrganizationSerializer(many=True, required=False, max_length=50)
    contact_info = ContactInfoSerializer(required=False, allow_null=True)
    
    def validate(self, attrs):
        """Validate the complete or partial profile data."""
        # For full validation, we need to merge with existing data if partial
        request = self.context.get('request')
        
        if request and request.method == 'PUT':
            # Full replacement - require personalInfo and summary
            if 'personalInfo' not in attrs:
                raise serializers.ValidationError({
                    'personalInfo': ['This field is required.']
                })
            if 'summary' not in attrs:
                raise serializers.ValidationError({
                    'summary': ['This field is required.']
                })
            
            # Validate against JSON schema
            data_for_validation = self._serialize_for_validation(attrs)
            validate_profile_data(data_for_validation)
        
        return attrs
    
    def _convert_to_json_serializable(self, obj):
        """Recursively convert UUIDs and dates to JSON-serializable format."""
        if isinstance(obj, uuid.UUID):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: self._convert_to_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_to_json_serializable(item) for item in obj]
        elif hasattr(obj, 'isoformat'):  # Date/datetime objects
            return obj.isoformat()
        else:
            return obj
    
    def _serialize_for_validation(self, data):
        """Convert validated data to JSON-serializable format."""
        return self._convert_to_json_serializable(data)
    
    def to_internal_value(self, data):
        """Override to handle date serialization."""
        validated = super().to_internal_value(data)
        return self._serialize_for_validation(validated)


class ProfileSaveEventSerializer(serializers.ModelSerializer):
    """Serializer for profile save history events."""

    label = serializers.SerializerMethodField()

    class Meta:
        model = ProfileSaveEvent
        fields = ['sections', 'saved_at', 'label']

    def get_label(self, obj) -> str:
        from app.profiles.services import build_save_event_label
        return build_save_event_label(obj.sections)
