"""
Custom exception handling for the Resume AI platform.

Implements the standardized error response format as per API contract:
{
    "error_code": "ERROR_CODE_ENUM",
    "message": "A human-readable explanation of the error.",
    "details": {...}
}
"""

import logging
from rest_framework.views import exception_handler
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import APIException
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404

logger = logging.getLogger(__name__)


# =============================================================================
# ERROR CODES (as per API contract)
# =============================================================================

class ErrorCode:
    """Machine-readable error codes."""
    AUTH_REQUIRED = 'AUTH_REQUIRED'
    INVALID_PAYLOAD = 'INVALID_PAYLOAD'
    TTL_EXPIRED = 'TTL_EXPIRED'
    MODEL_OUTPUT_INVALID = 'MODEL_OUTPUT_INVALID'
    LATEX_COMPILE_ERROR = 'LATEX_COMPILE_ERROR'
    LATEX_VALIDATION_FAILED = 'LATEX_VALIDATION_FAILED'
    RATE_LIMITED = 'RATE_LIMITED'
    NOT_FOUND = 'NOT_FOUND'
    INTERNAL_SERVER_ERROR = 'INTERNAL_SERVER_ERROR'
    AI_SERVICE_ERROR = 'AI_SERVICE_ERROR'
    AI_SERVICE_QUOTA_EXCEEDED = 'AI_SERVICE_QUOTA_EXCEEDED'
    LATEX_SERVICE_ERROR = 'LATEX_SERVICE_ERROR'
    GENERATION_TIMEOUT = 'GENERATION_TIMEOUT'
    EMAIL_NOT_VERIFIED = 'EMAIL_NOT_VERIFIED'
    INVALID_TOKEN = 'INVALID_TOKEN'
    # Auth-specific error codes
    INVALID_CREDENTIALS = 'INVALID_CREDENTIALS'
    EMAIL_ALREADY_REGISTERED = 'EMAIL_ALREADY_REGISTERED'
    ACCOUNT_LOCKED = 'ACCOUNT_LOCKED'
    INVALID_PASSWORD = 'INVALID_PASSWORD'
    # Field-level error codes
    INVALID_EMAIL_FORMAT = 'INVALID_EMAIL_FORMAT'
    PASSWORD_TOO_WEAK = 'PASSWORD_TOO_WEAK'
    PASSWORD_MISMATCH = 'PASSWORD_MISMATCH'


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class BaseAPIException(APIException):
    """
    Base exception class for custom API exceptions.
    All custom exceptions inherit from this.
    """
    error_code = ErrorCode.INTERNAL_SERVER_ERROR
    default_message = 'An unexpected error occurred.'
    default_status = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message=None, details=None, error_code=None, errors=None):
        self.error_code = error_code or self.error_code
        self.message = message or self.default_message
        self.details = details
        self.errors = errors  # New: structured field-level errors
        self.status_code = self.default_status
        super().__init__(detail=self.message)


class AuthenticationRequiredException(BaseAPIException):
    """Raised when authentication is required but not provided."""
    error_code = ErrorCode.AUTH_REQUIRED
    default_message = 'Authentication credentials were not provided.'
    default_status = status.HTTP_401_UNAUTHORIZED


class EmailNotVerifiedException(BaseAPIException):
    """Raised when the user's email is not verified."""
    error_code = ErrorCode.EMAIL_NOT_VERIFIED
    default_message = 'Email verification is required to access this resource.'
    default_status = status.HTTP_403_FORBIDDEN


class InvalidPayloadException(BaseAPIException):
    """Raised when request payload is invalid."""
    error_code = ErrorCode.INVALID_PAYLOAD
    default_message = 'Invalid input.'
    default_status = status.HTTP_400_BAD_REQUEST


class InvalidTokenException(BaseAPIException):
    """Raised when a verification token is invalid or expired."""
    error_code = ErrorCode.INVALID_TOKEN
    default_message = 'Invalid or expired token.'
    default_status = status.HTTP_400_BAD_REQUEST


class EmailAlreadyRegisteredException(BaseAPIException):
    """Raised when attempting to register with an email that already exists."""
    error_code = ErrorCode.EMAIL_ALREADY_REGISTERED
    default_message = 'Account already exists. Try logging in.'
    default_status = status.HTTP_409_CONFLICT


class TTLExpiredException(BaseAPIException):
    """Raised when accessing an expired resource."""
    error_code = ErrorCode.TTL_EXPIRED
    default_message = 'This resource has expired and is no longer available.'
    default_status = status.HTTP_410_GONE


class ResourceNotFoundException(BaseAPIException):
    """Raised when a requested resource is not found."""
    error_code = ErrorCode.NOT_FOUND
    default_message = 'The requested resource was not found.'
    default_status = status.HTTP_404_NOT_FOUND


class ModelOutputInvalidException(BaseAPIException):
    """Raised when AI model produces invalid/hallucinated output."""
    error_code = ErrorCode.MODEL_OUTPUT_INVALID
    default_message = 'The AI model produced invalid output that could not be validated.'
    default_status = status.HTTP_500_INTERNAL_SERVER_ERROR


class LatexCompileException(BaseAPIException):
    """Raised when LaTeX fails to compile."""
    error_code = ErrorCode.LATEX_COMPILE_ERROR
    default_message = 'The generated LaTeX source failed to compile into a PDF.'
    default_status = status.HTTP_500_INTERNAL_SERVER_ERROR


class AIServiceException(BaseAPIException):
    """Raised when the AI service encounters an error."""
    error_code = ErrorCode.AI_SERVICE_ERROR
    default_message = 'The AI service encountered an error.'
    default_status = status.HTTP_503_SERVICE_UNAVAILABLE


class AIServiceQuotaExceededException(BaseAPIException):
    """Raised when AI service quota is exceeded."""
    error_code = ErrorCode.AI_SERVICE_QUOTA_EXCEEDED
    default_message = 'AI service quota exceeded. Please try again later.'
    default_status = status.HTTP_503_SERVICE_UNAVAILABLE


class LatexServiceException(BaseAPIException):
    """Raised when the LaTeX service encounters an error."""
    error_code = ErrorCode.LATEX_SERVICE_ERROR
    default_message = 'The LaTeX compilation service encountered an error.'
    default_status = status.HTTP_503_SERVICE_UNAVAILABLE


class RateLimitedException(BaseAPIException):
    """Raised when user exceeds rate limits."""
    error_code = ErrorCode.RATE_LIMITED
    default_message = 'Request was throttled. Try again later.'
    default_status = status.HTTP_429_TOO_MANY_REQUESTS


class GenerationTimeoutException(BaseAPIException):
    """Raised when resume generation exceeds time limit."""
    error_code = ErrorCode.GENERATION_TIMEOUT
    default_message = 'Resume generation timed out. Please try again.'
    default_status = status.HTTP_504_GATEWAY_TIMEOUT


# =============================================================================
# CUSTOM EXCEPTION HANDLER
# =============================================================================

def custom_exception_handler(exc, context):
    """
    Custom exception handler that formats all errors according to the API contract.
    
    Response format:
    {
        "error_code": "ERROR_CODE",
        "message": "Human readable message",
        "details": {...} (optional)
    }
    """
    # Call DRF's default exception handler first
    response = exception_handler(exc, context)

    # Handle our custom exceptions
    if isinstance(exc, BaseAPIException):
        # Support new format with 'code' and 'errors' array for auth endpoints
        if exc.errors is not None:
            error_response = {
                'code': exc.error_code,
                'message': exc.message,
                'errors': exc.errors,
            }
        else:
            # Legacy format with 'error_code' and 'details'
            error_response = {
                'error_code': exc.error_code,
                'message': exc.message,
            }
            if exc.details:
                error_response['details'] = exc.details
        return Response(error_response, status=exc.status_code)

    # Handle Django's validation errors
    if isinstance(exc, DjangoValidationError):
        return Response({
            'error_code': ErrorCode.INVALID_PAYLOAD,
            'message': 'Validation error.',
            'details': exc.message_dict if hasattr(exc, 'message_dict') else {'non_field_errors': exc.messages}
        }, status=status.HTTP_400_BAD_REQUEST)

    # Handle 404
    if isinstance(exc, Http404):
        return Response({
            'error_code': ErrorCode.NOT_FOUND,
            'message': str(exc) if str(exc) != 'Not found.' else 'The requested resource was not found.',
        }, status=status.HTTP_404_NOT_FOUND)

    # If we got a response from DRF's handler, format it
    if response is not None:
        # Map DRF status codes to our error codes
        error_code_map = {
            400: ErrorCode.INVALID_PAYLOAD,
            401: ErrorCode.AUTH_REQUIRED,
            403: ErrorCode.AUTH_REQUIRED,
            404: ErrorCode.NOT_FOUND,
            429: ErrorCode.RATE_LIMITED,
        }
        
        error_code = error_code_map.get(
            response.status_code, 
            ErrorCode.INTERNAL_SERVER_ERROR
        )
        
        # Extract message from response data
        detail = response.data
        if isinstance(detail, dict):
            message = detail.pop('detail', None) or 'An error occurred.'
            details = detail if detail else None
        elif isinstance(detail, list):
            message = '; '.join(str(d) for d in detail)
            details = None
        else:
            message = str(detail)
            details = None
        
        error_response = {
            'error_code': error_code,
            'message': message,
        }
        if details:
            error_response['details'] = details
        
        # Per OpenAPI spec: AUTH_REQUIRED must return 401, not 403
        # DRF's IsAuthenticated returns 403 for unauthenticated users,
        # but our API contract requires 401 Unauthorized
        if response.status_code == 403 and error_code == ErrorCode.AUTH_REQUIRED:
            response.status_code = status.HTTP_401_UNAUTHORIZED
            
        response.data = error_response
        return response

    # Unhandled exception - log error but NOT full exception
    # to prevent PII leakage in request data
    # Use logger.error instead of logger.exception to avoid traceback
    # which may contain sensitive request data
    logger.error(
        "Unhandled exception in view %s: %s - %s",
        context.get('view').__class__.__name__ if context.get('view') else 'unknown',
        type(exc).__name__,
        str(exc)[:200]  # Truncate to avoid logging large payloads
    )
    
    return Response({
        'error_code': ErrorCode.INTERNAL_SERVER_ERROR,
        'message': 'An unexpected error occurred.',
    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
