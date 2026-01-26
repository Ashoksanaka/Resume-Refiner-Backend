"""
Resume API views for the Resume AI platform.

Implements the resume endpoints as per OpenAPI spec:
- POST /jds
- GET /jds/{jd_id}
- DELETE /jds/{jd_id}
- GET /resumes
- POST /resumes
- GET /resumes/{generation_id}/status
- GET /resumes/{generation_id}/download
- GET /resumes/{generation_id}/source
"""

import logging
from pathlib import Path
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from django.http import FileResponse
from app.resumes.serializers import (
    JobDescriptionSerializer,
    JobDescriptionCreateSerializer,
    ResumeGenerationRequestSerializer,
    ResumeGenerationCreateSerializer,
    ResumeSourceSerializer,
)
from app.resumes.services import (
    JobDescriptionService,
    ResumeGenerationService,
)
from app.resumes.tasks import process_resume_generation
from app.authentication.services import AuthenticationService
from app.common.exceptions import (
    InvalidPayloadException,
    ResourceNotFoundException,
    TTLExpiredException,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Job Description Views
# =============================================================================

class JobDescriptionListCreateView(APIView):
    """
    POST /jds
    
    Create a new job description.
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        POST /jds
        
        Ingest a new job description.
        
        Request: {text}
        Response: 201 Created with JobDescription object
        """
        # Require verified email
        AuthenticationService.require_verified_email(request.user)
        
        serializer = JobDescriptionCreateSerializer(data=request.data)
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        jd = JobDescriptionService.create_job_description(
            user=request.user,
            text=serializer.validated_data['text']
        )
        
        return Response(
            JobDescriptionSerializer(jd).data,
            status=status.HTTP_201_CREATED
        )


class JobDescriptionDetailView(APIView):
    """
    GET, DELETE /jds/{jd_id}
    
    Get or delete a specific job description.
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request, jd_id):
        """
        GET /jds/{jd_id}
        
        Get a specific job description.
        
        Response: 200 OK with JobDescription object
        Response: 404 Not Found
        Response: 410 Gone (TTL expired)
        """
        AuthenticationService.require_verified_email(request.user)
        
        jd = JobDescriptionService.get_job_description(request.user, jd_id)
        return Response(
            JobDescriptionSerializer(jd).data,
            status=status.HTTP_200_OK
        )
    
    def delete(self, request, jd_id):
        """
        DELETE /jds/{jd_id}
        
        Delete a job description.
        
        Response: 204 No Content
        Response: 404 Not Found
        """
        AuthenticationService.require_verified_email(request.user)
        
        JobDescriptionService.delete_job_description(request.user, jd_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Resume Generation Views
# =============================================================================

class ResumeGenerationThrottle(ScopedRateThrottle):
    """Custom throttle for resume generation (POST only)."""
    scope = 'resume_generation'


class StatusCheckThrottle(ScopedRateThrottle):
    """High-frequency throttle for status polling."""
    scope = 'status_check'


class ResumeListCreateView(APIView):
    """
    GET, POST /resumes
    
    List all resume generation requests or trigger a new one.
    """
    
    permission_classes = [IsAuthenticated]
    # Only apply strict throttle to POST (generation), not GET (listing)
    throttle_classes = []
    
    def get_throttles(self):
        """Apply different throttles based on HTTP method."""
        if self.request.method == 'POST':
            return [ResumeGenerationThrottle()]
        return []  # No throttle for GET (uses default user throttle)
    
    def get(self, request):
        """
        GET /resumes
        
        List all resume generation requests for the user.
        
        Response: 200 OK with array of ResumeGenerationRequest objects
        """
        AuthenticationService.require_verified_email(request.user)
        
        requests = ResumeGenerationService.list_generation_requests(request.user)
        serializer = ResumeGenerationRequestSerializer(requests, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def post(self, request):
        """
        POST /resumes
        
        Trigger a new resume generation.
        
        Headers: Idempotency-Key (optional, UUID)
        Request: {job_description_id, template_id}
        Response: 202 Accepted with ResumeGenerationRequest object
        """
        AuthenticationService.require_verified_email(request.user)
        
        # Check idempotency
        idempotency_key = request.headers.get('Idempotency-Key')
        if idempotency_key:
            cached_response = ResumeGenerationService.check_idempotency(
                request.user,
                idempotency_key,
                'POST /resumes'
            )
            if cached_response:
                return Response(
                    cached_response['body'],
                    status=cached_response['status']
                )
        
        # Validate request
        serializer = ResumeGenerationCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        # Use default template if not provided
        template_id = serializer.validated_data.get('template_id', 'tccv')
        
        # Create generation request
        generation_request = ResumeGenerationService.create_generation_request(
            user=request.user,
            job_description_id=str(serializer.validated_data['job_description_id']),
            template_id=template_id,
            idempotency_key=idempotency_key,
        )
        
        # Trigger async processing
        process_resume_generation.delay(str(generation_request.id))
        
        # Prepare response
        response_data = ResumeGenerationRequestSerializer(generation_request).data
        
        # Store idempotency key
        if idempotency_key:
            ResumeGenerationService.store_idempotency(
                request.user,
                idempotency_key,
                'POST /resumes',
                status.HTTP_202_ACCEPTED,
                response_data
            )
        
        return Response(response_data, status=status.HTTP_202_ACCEPTED)


class ResumeStatusView(APIView):
    """
    GET /resumes/{generation_id}/status
    
    Get the status of a resume generation task.
    This endpoint is polled frequently during generation, so uses a high rate limit.
    """
    
    permission_classes = [IsAuthenticated]
    throttle_classes = [StatusCheckThrottle]
    
    def get(self, request, generation_id):
        """
        GET /resumes/{generation_id}/status
        
        Response: 200 OK with ResumeGenerationRequest object
        Response: 404 Not Found
        Response: 410 Gone (TTL expired)
        """
        AuthenticationService.require_verified_email(request.user)
        
        generation_request = ResumeGenerationService.get_generation_request(
            request.user,
            generation_id
        )
        
        return Response(
            ResumeGenerationRequestSerializer(generation_request).data,
            status=status.HTTP_200_OK
        )


class ResumeDownloadView(APIView):
    """
    GET /resumes/{generation_id}/download
    
    Download the generated PDF resume.
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request, generation_id):
        """
        GET /resumes/{generation_id}/download
        
        Query parameters:
        - inline: If 'true', display PDF inline (for preview). Default: 'false' (download as attachment)
        
        Response: 200 OK with PDF binary
        Response: 404 Not Found (or generation not complete/failed)
        Response: 410 Gone (TTL expired)
        """
        AuthenticationService.require_verified_email(request.user)
        
        generation_request = ResumeGenerationService.get_generation_request(
            request.user,
            generation_id
        )
        
        # Check if generation is complete
        if generation_request.status != 'success':
            raise ResourceNotFoundException(
                'Resume is not ready. Current status: ' + generation_request.status
            )
        
        # Check if PDF exists
        if not generation_request.generated_pdf_path:
            raise ResourceNotFoundException('PDF file not found.')
        
        pdf_path = Path(generation_request.generated_pdf_path)
        if not pdf_path.exists():
            raise ResourceNotFoundException('PDF file not found on disk.')
        
        # Check if inline preview is requested
        inline_preview = request.query_params.get('inline', 'false').lower() == 'true'
        
        # Prepare filename
        filename = f"resume_{generation_id}.pdf"
        
        # Return PDF file - open in binary mode for FileResponse
        # FileResponse will close the file automatically
        response = FileResponse(
            open(pdf_path, 'rb'),
            as_attachment=not inline_preview,  # Attachment for download, inline for preview
            filename=filename,
            content_type='application/pdf'
        )
        
        # Explicitly set Content-Disposition header to ensure proper filename
        # This is critical for browsers to use the correct filename instead of URL path
        # Use both standard and RFC 5987 format for maximum browser compatibility
        import urllib.parse
        encoded_filename = urllib.parse.quote(filename)
        
        if not inline_preview:
            # Format: attachment; filename="resume_xxx.pdf"; filename*=UTF-8''resume_xxx.pdf
            response['Content-Disposition'] = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{encoded_filename}'
        else:
            response['Content-Disposition'] = f'inline; filename="{filename}"'
        
        return response


class ResumeSourceView(APIView):
    """
    GET /resumes/{generation_id}/source
    
    Get the AI-generated LaTeX source.
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request, generation_id):
        """
        GET /resumes/{generation_id}/source
        
        Response: 200 OK with {latex_source, modifications}
        Response: 404 Not Found (or generation not complete/failed)
        Response: 410 Gone (TTL expired)
        """
        AuthenticationService.require_verified_email(request.user)
        
        generation_request = ResumeGenerationService.get_generation_request(
            request.user,
            generation_id
        )
        
        # Check if generation is complete
        if generation_request.status != 'success':
            raise ResourceNotFoundException(
                'Resume source is not available. Current status: ' + generation_request.status
            )
        
        serializer = ResumeSourceSerializer({
            'latex_source': generation_request.generated_latex or '',
            'modifications': generation_request.modifications or [],
        })
        
        return Response(serializer.data, status=status.HTTP_200_OK)


# =============================================================================
# Health Check View
# =============================================================================

class HealthCheckView(APIView):
    """
    GET /health
    
    Check the health of the service.
    """
    
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        GET /health
        
        Response: 200 OK with {status: "ok"}
        """
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)
