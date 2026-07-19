"""
Serializers for resume-related endpoints.

As per API contract:
- POST /jds: {role_name, text} -> JobDescription
- GET /jds/{id}: JobDescription
- POST /resumes: {job_description_id, template_id?, sections} -> ResumeGenerationRequest
- GET /resumes: [ResumeGenerationRequest]
- GET /resumes/{id}/status: ResumeGenerationRequest
- GET /resumes/{id}/source: {latex_source, modifications}
"""

from rest_framework import serializers
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.resumes.services import ALLOWED_PROFILE_SECTIONS
from app.common.models import Template


class JobDescriptionSerializer(serializers.ModelSerializer):
    """
    Serializer for JobDescription model.
    
    Response schema:
    {
        "id": "<uuid>",
        "role_name": "<role_title>",
        "text": "<job_description_text>",
        "created_at": "<iso_datetime>",
        "expires_at": "<iso_datetime>"
    }
    """
    
    class Meta:
        model = JobDescription
        fields = ['id', 'role_name', 'text', 'created_at', 'expires_at']
        read_only_fields = ['id', 'created_at', 'expires_at']


class JobDescriptionCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new job description.
    
    Request:
    {
        "role_name": "<target_role_title>",
        "text": "<job_description_text>" (min 50, max 20000 chars)
    }
    
    SECURITY: Validates minimum length to ensure meaningful JD content.
    """
    
    role_name = serializers.CharField(min_length=2, max_length=200)
    text = serializers.CharField(min_length=50, max_length=20000)
    
    def validate_role_name(self, value):
        role_name = value.strip()
        if len(role_name) < 2:
            raise serializers.ValidationError('Role name must be at least 2 characters.')
        return role_name

    def validate_text(self, value):
        """Validate that text is meaningful after stripping."""
        text = value.strip()
        if not text:
            raise serializers.ValidationError('Job description text cannot be empty.')
        if len(text) < 50:
            raise serializers.ValidationError(
                'Job description must be at least 50 characters to be meaningful.'
            )
        return text


class ResumeGenerationRequestSerializer(serializers.ModelSerializer):
    """
    Serializer for ResumeGenerationRequest model.
    
    Response schema:
    {
        "id": "<uuid>",
        "status": "pending|processing|success|failed|cancelled",
        "failure_reason": "<string>|null",
        "created_at": "<iso_datetime>",
        "expires_at": "<iso_datetime>"
    }
    """
    
    failure_reason = serializers.CharField(read_only=True)

    class Meta:
        model = ResumeGenerationRequest
        fields = [
            'id',
            'status',
            'failure_reason',
            'created_at',
            'expires_at',
        ]
        read_only_fields = fields


class ResumeGenerationCreateSerializer(serializers.Serializer):
    """
    Serializer for triggering a new resume generation.
    
    Request:
    {
        "job_description_id": "<uuid>",
        "template_id": "<string>" (optional, defaults to 'main'),
        "sections": ["experience", "education", ...]
    }
    """
    
    job_description_id = serializers.UUIDField()
    template_id = serializers.CharField(max_length=100, required=False, default='main', write_only=True)
    sections = serializers.ListField(
        child=serializers.CharField(max_length=50),
        min_length=1,
    )
    
    def validate_job_description_id(self, value):
        """Validate that the job description exists and belongs to the user."""
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError('Authentication required.')
        
        try:
            jd = JobDescription.objects.get(id=value, user=request.user)
        except JobDescription.DoesNotExist:
            raise serializers.ValidationError('Job description not found.')
        
        if jd.is_expired:
            raise serializers.ValidationError('Job description has expired.')
        
        return value
    
    def validate_template_id(self, value):
        """Validate that the template exists and is active."""
        if not Template.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError('Template not found or not available.')
        return value

    def validate_sections(self, value):
        invalid = [key for key in value if key not in ALLOWED_PROFILE_SECTIONS]
        if invalid:
            raise serializers.ValidationError(
                f'Invalid profile section keys: {", ".join(sorted(set(invalid)))}'
            )
        return list(dict.fromkeys(value))


class ResumeSourceSerializer(serializers.Serializer):
    """
    Serializer for resume source endpoint.
    
    Response:
    {
        "latex_source": "<latex_code>",
        "modifications": ["<modification_summary>", ...]
    }
    """
    
    latex_source = serializers.CharField()
    modifications = serializers.ListField(
        child=serializers.CharField(),
        default=list
    )


# TemplateSerializer removed - template selection feature has been removed
# Templates are now managed internally and users cannot select them
