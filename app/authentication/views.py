"""
Authentication API views for the Resume AI platform.

Implements the auth endpoints as per OpenAPI spec:
- POST /auth/signup
- POST /auth/verify
- POST /auth/resend-verification
- POST /auth/login
- POST /auth/logout
- GET /auth/me

SECURITY:
- Rate limiting on sensitive endpoints
- Timing-safe authentication to prevent enumeration
- Session rotation on login
"""

import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from django.contrib.auth import login, logout
from django.contrib.auth.hashers import make_password
from decouple import config
from app.authentication.serializers import (
    UserSerializer,
    SignupSerializer,
    VerifyEmailSerializer,
    LoginSerializer,
    ResendVerificationSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
)
from rest_framework import serializers
from app.authentication.services import AuthenticationService
from app.authentication.models import User
from app.common.exceptions import (
    InvalidPayloadException, 
    ResourceNotFoundException,
    EmailAlreadyRegisteredException,
    ErrorCode,
)

logger = logging.getLogger(__name__)


class ResendVerificationThrottle(AnonRateThrottle):
    """Strict rate limiting for resend verification to prevent abuse."""
    rate = '3/hour'


class LoginThrottle(AnonRateThrottle):
    """Rate limiting for login to prevent brute force attacks."""
    rate = '5/minute'


class SignupThrottle(AnonRateThrottle):
    """Rate limiting for signup to prevent abuse."""
    rate = '10/hour'


class SignupView(APIView):
    """
    POST /auth/signup
    
    Register a new user. Sends verification email.
    
    Request: {email, password, confirm_password}
    Response: 201 Created (verification email sent)
    """
    
    permission_classes = [AllowAny]
    throttle_classes = [SignupThrottle]
    
    def post(self, request):
        # Log incoming request data for debugging (without logging passwords)
        request_data_copy = dict(request.data)
        if 'password' in request_data_copy:
            request_data_copy['password'] = '[REDACTED]'
        if 'confirm_password' in request_data_copy:
            request_data_copy['confirm_password'] = '[REDACTED]'
        logger.info("Signup request received with fields: %s", list(request_data_copy.keys()))
        
        # Check for duplicate email first (before serializer validation)
        email = request.data.get('email', '').lower()
        if email and User.objects.filter(email=email).exists():
            raise EmailAlreadyRegisteredException()
        
        serializer = SignupSerializer(data=request.data)
        
        if not serializer.is_valid():
            errors = serializer.errors
            logger.warning("Signup validation failed. Errors: %s", errors)
            logger.warning("Request data keys: %s", list(request.data.keys()))
            field_errors = []
            
            # Process field errors
            for field, field_error_list in errors.items():
                # Handle list of errors
                if isinstance(field_error_list, list):
                    for error_item in field_error_list:
                        error_code = None
                        error_str = str(error_item).lower()
                        
                        # Map error message to error code
                        if field == 'email':
                            if 'already' in error_str or 'exists' in error_str:
                                raise EmailAlreadyRegisteredException()
                            elif 'invalid' in error_str or 'format' in error_str or 'valid' in error_str or 'enter a valid' in error_str:
                                error_code = ErrorCode.INVALID_EMAIL_FORMAT
                            elif 'required' in error_str:
                                error_code = ErrorCode.INVALID_EMAIL_FORMAT
                        elif field == 'password':
                            if 'required' in error_str:
                                error_code = ErrorCode.PASSWORD_TOO_WEAK
                            else:
                                error_code = ErrorCode.PASSWORD_TOO_WEAK
                        elif field == 'confirm_password':
                            if 'required' in error_str:
                                error_code = ErrorCode.PASSWORD_MISMATCH
                            else:
                                error_code = ErrorCode.PASSWORD_MISMATCH
                        
                        if error_code:
                            field_errors.append({
                                'field': field,
                                'code': error_code
                            })
                        else:
                            # Fallback for unhandled errors - still add them with generic code
                            if field in ['email', 'password', 'confirm_password']:
                                if field == 'email':
                                    field_errors.append({
                                        'field': field,
                                        'code': ErrorCode.INVALID_EMAIL_FORMAT
                                    })
                                elif field == 'password':
                                    field_errors.append({
                                        'field': field,
                                        'code': ErrorCode.PASSWORD_TOO_WEAK
                                    })
                                elif field == 'confirm_password':
                                    field_errors.append({
                                        'field': field,
                                        'code': ErrorCode.PASSWORD_MISMATCH
                                    })
                
                # Handle dict errors (for nested validation errors)
                elif isinstance(field_error_list, dict):
                    if field == 'confirm_password':
                        field_errors.append({
                            'field': 'confirm_password',
                            'code': ErrorCode.PASSWORD_MISMATCH
                        })
                    else:
                        # Handle other dict errors
                        field_errors.append({
                            'field': field,
                            'code': ErrorCode.INVALID_PAYLOAD
                        })
                
                # Handle string errors
                else:
                    error_str = str(field_error_list).lower()
                    if field == 'email':
                        if 'already' in error_str or 'exists' in error_str:
                            raise EmailAlreadyRegisteredException()
                        elif 'invalid' in error_str or 'format' in error_str or 'valid' in error_str:
                            field_errors.append({
                                'field': field,
                                'code': ErrorCode.INVALID_EMAIL_FORMAT
                            })
                    elif field == 'password':
                        field_errors.append({
                            'field': field,
                            'code': ErrorCode.PASSWORD_TOO_WEAK
                        })
                    elif field == 'confirm_password':
                        field_errors.append({
                            'field': field,
                            'code': ErrorCode.PASSWORD_MISMATCH
                        })
                    else:
                        # Handle any other field errors
                        field_errors.append({
                            'field': field,
                            'code': ErrorCode.INVALID_PAYLOAD
                        })
            
            # Ensure we have at least one error
            if not field_errors:
                # If no specific field errors were identified, add a generic one
                field_errors.append({
                    'field': 'non_field_errors',
                    'code': ErrorCode.INVALID_PAYLOAD
                })
            
            # Return structured validation errors
            raise InvalidPayloadException(
                message='Validation failed.',
                errors=field_errors
            )
        
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        
        # Double-check for duplicate email (race condition protection)
        if User.objects.filter(email=email.lower()).exists():
            raise EmailAlreadyRegisteredException()
        
        # Create user
        user = AuthenticationService.create_user(email, password)
        
        # Generate and send verification token
        token = AuthenticationService.generate_verification_token(user)
        AuthenticationService.send_verification_email(user, token)
        
        logger.info("User signup successful: %s", user.id)
        
        return Response(
            {'message': 'Verification email sent'},
            status=status.HTTP_201_CREATED
        )


class VerifyEmailView(APIView):
    """
    POST /auth/verify
    
    Verify email with token.
    
    Request: {token}
    Response: 200 OK (user verified)
    """
    
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        token = serializer.validated_data['token']
        
        # Verify email (raises InvalidTokenException if invalid)
        user = AuthenticationService.verify_email(token)
        
        return Response(
            {'message': 'Email verified successfully.'},
            status=status.HTTP_200_OK
        )


class ResendVerificationView(APIView):
    """
    POST /auth/resend-verification
    
    Resend verification email to an unverified user.
    
    Request: {email}
    Response: 202 Accepted (always, to prevent email enumeration)
    """
    
    permission_classes = [AllowAny]
    throttle_classes = [ResendVerificationThrottle]
    
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        email = serializer.validated_data['email'].lower()
        
        # Always return 202 to prevent email enumeration attacks
        try:
            user = User.objects.get(email=email)
            
            if not user.is_verified:
                # Generate new token and send email
                token = AuthenticationService.generate_verification_token(user)
                AuthenticationService.send_verification_email(user, token)
                logger.info("Resent verification email for user: %s", user.id)
            else:
                logger.info("User already verified, skipping resend: %s", user.id)
                
        except User.DoesNotExist:
            # Don't reveal that email doesn't exist
            logger.info("Resend verification attempted for non-existent email")
        
        return Response(
            {'message': 'If this email is registered and unverified, a verification email has been sent.'},
            status=status.HTTP_202_ACCEPTED
        )


class LoginView(APIView):
    """
    POST /auth/login
    
    Log in a user.
    
    Request: {email, password}
    Response: 200 OK with User object (session cookie is set)
    
    SECURITY:
    - Rate limited to prevent brute force
    - Timing-safe validation to prevent enumeration
    - Session rotation to prevent fixation
    - Detailed errors configurable via AUTH_DETAILED_ERRORS env flag
    """
    
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    
    def post(self, request):
        # Check if detailed errors are enabled
        detailed_errors = config('AUTH_DETAILED_ERRORS', default=False, cast=bool)
        
        serializer = LoginSerializer(
            data=request.data, 
            context={'request': request},
            detailed_errors=detailed_errors
        )
        
        if not serializer.is_valid():
            # Default error response (secure - prevents enumeration)
            error_code = ErrorCode.INVALID_CREDENTIALS
            error_message = 'Invalid email or password.'
            
            # If detailed errors are enabled, check for specific error code from serializer
            if detailed_errors and hasattr(serializer, 'login_error_code'):
                error_code = serializer.login_error_code
                if error_code == ErrorCode.EMAIL_NOT_VERIFIED:
                    error_message = 'Email verification is required.'
                elif error_code == ErrorCode.INVALID_PASSWORD:
                    error_message = 'Invalid password.'
                elif error_code == ErrorCode.ACCOUNT_LOCKED:
                    error_message = 'Account is locked.'
            
            logger.info("Login failed: %s", error_code)
            
            return Response(
                {
                    'code': error_code,
                    'message': error_message,
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        user = serializer.validated_data['user']
        
        # Rotate session ID to prevent session fixation attacks
        request.session.cycle_key()
        
        # Create session
        login(request, user)
        
        # Also generate JWT for API access
        result = AuthenticationService.login_user(user)
        
        logger.info("Login successful: %s", user.id)
        
        # Return user data with optional token
        response_data = UserSerializer(user).data
        response_data['access_token'] = result['access_token']
        
        return Response(response_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    POST /auth/logout
    
    Log out a user.
    
    Response: 204 No Content
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """
    GET /auth/me
    
    Get current authenticated user.
    
    Response: 200 OK with User object
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ForgotPasswordThrottle(AnonRateThrottle):
    """Strict rate limiting for password reset to prevent abuse."""
    rate = '3/hour'


class ForgotPasswordView(APIView):
    """
    POST /auth/forgot-password
    
    Request password reset email.
    
    Request: {email}
    Response: 202 Accepted (always, to prevent email enumeration)
    
    SECURITY: Always returns 202 to prevent email enumeration.
    """
    
    permission_classes = [AllowAny]
    throttle_classes = [ForgotPasswordThrottle]
    
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        email = serializer.validated_data['email'].lower()
        
        # Always return 202 to prevent email enumeration attacks
        try:
            user = User.objects.get(email=email)
            
            # Generate and send reset token
            token = AuthenticationService.generate_password_reset_token(user)
            AuthenticationService.send_password_reset_email(user, token)
            logger.info("Password reset email requested for user: %s", user.id)
                
        except User.DoesNotExist:
            # Don't reveal that email doesn't exist
            # But still perform some work to normalize timing
            make_password('dummy_password')
            logger.info("Password reset attempted for non-existent email")
        
        return Response(
            {'message': 'If this email is registered, a password reset link has been sent.'},
            status=status.HTTP_202_ACCEPTED
        )


class ResetPasswordView(APIView):
    """
    POST /auth/reset-password
    
    Reset password using token.
    
    Request: {token, password}
    Response: 200 OK (password reset successfully)
    """
    
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        token = serializer.validated_data['token']
        password = serializer.validated_data['password']
        
        # Reset password (raises InvalidTokenException if invalid)
        AuthenticationService.reset_password(token, password)
        
        return Response(
            {'message': 'Password has been reset successfully.'},
            status=status.HTTP_200_OK
        )


class PasswordPolicyView(APIView):
    """
    GET /auth/password-policy
    
    Get password policy requirements.
    
    Response: 200 OK with password policy details
    """
    
    permission_classes = [AllowAny]
    
    def get(self, request):
        return Response(
            {
                'min_length': 10,
                'require_uppercase': True,
                'require_number': True,
                'require_symbol': True
            },
            status=status.HTTP_200_OK
        )


class PasswordStrengthSerializer(serializers.Serializer):
    """Serializer for password strength check."""
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'}
    )


class PasswordStrengthView(APIView):
    """
    POST /auth/password-strength
    
    Check password strength without storing or logging the password.
    
    Request: {password}
    Response: 200 OK with strength score and validity
    
    SECURITY: Password is evaluated in-memory only, never logged or persisted.
    """
    
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = PasswordStrengthSerializer(data=request.data)
        
        if not serializer.is_valid():
            raise InvalidPayloadException(
                message='Invalid input.',
                details=serializer.errors
            )
        
        password = serializer.validated_data['password']
        
        # Calculate password strength score (0-100)
        score = 0
        valid = True
        
        # Length check (max 30 points)
        length = len(password)
        if length >= 10:
            score += min(30, (length - 10) * 2)
        else:
            valid = False
        
        # Character variety checks (20 points each, max 70 points)
        if any(c.isupper() for c in password):
            score += 20
        else:
            valid = False
        
        if any(c.islower() for c in password):
            score += 10
        
        if any(c.isdigit() for c in password):
            score += 20
        else:
            valid = False
        
        if any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
            score += 20
        else:
            valid = False
        
        # Bonus for length beyond minimum
        if length > 12:
            score += min(10, (length - 12))
        
        # Cap score at 100
        score = min(100, score)
        
        # Never log the password - only log that a check was performed
        logger.info("Password strength check performed (score: %d, valid: %s)", score, valid)
        
        return Response(
            {
                'score': score,
                'valid': valid
            },
            status=status.HTTP_200_OK
        )
