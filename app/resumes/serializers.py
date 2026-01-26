"""
Serializers for resume-related endpoints.

As per API contract:
- POST /jds: {text} -> JobDescription
- GET /jds/{id}: JobDescription
- POST /resumes: {job_description_id, template_id?} -> ResumeGenerationRequest
- GET /resumes: [ResumeGenerationRequest]
- GET /resumes/{id}/status: ResumeGenerationRequest
- GET /resumes/{id}/source: {latex_source, modifications}
"""

from rest_framework import serializers
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.common.models import Template


class JobDescriptionSerializer(serializers.ModelSerializer):
    """
    Serializer for JobDescription model.
    
    Response schema:
    {
        "id": "<uuid>",
        "text": "<job_description_text>",
        "created_at": "<iso_datetime>",
        "expires_at": "<iso_datetime>"
    }
    """
    
    class Meta:
        model = JobDescription
        fields = ['id', 'text', 'created_at', 'expires_at']
        read_only_fields = ['id', 'created_at', 'expires_at']


class JobDescriptionCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new job description.
    
    Request:
    {
        "text": "<job_description_text>" (min 50, max 20000 chars)
    }
    
    SECURITY: Validates minimum length to ensure meaningful JD content.
    """
    
    text = serializers.CharField(min_length=50, max_length=20000)
    
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
        "status": "pending|processing|success|failed",
        "failure_reason": "<string>|null",
        "created_at": "<iso_datetime>",
        "expires_at": "<iso_datetime>"
    }
    """
    
    class Meta:
        model = ResumeGenerationRequest
        fields = ['id', 'status', 'failure_reason', 'created_at', 'expires_at']
        read_only_fields = ['id', 'status', 'failure_reason', 'created_at', 'expires_at']


class ResumeGenerationCreateSerializer(serializers.Serializer):
    """
    Serializer for triggering a new resume generation.
    
    Request:
    {
        "job_description_id": "<uuid>",
        "template_id": "<string>" (optional, defaults to 'tccv')
    }
    """
    
    job_description_id = serializers.UUIDField()
    template_id = serializers.CharField(max_length=100, required=False, default='tccv', write_only=True)
    
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
