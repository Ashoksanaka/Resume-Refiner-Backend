"""
Serializers for authentication endpoints.

As per API contract:
- POST /auth/signup: {email, password}
- POST /auth/verify: {token}
- POST /auth/login: {email, password}
- GET /auth/me: returns User schema
"""

from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from app.authentication.models import User
from app.common.exceptions import ErrorCode


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for User model.
    
    Response schema:
    {
        "id": "<uuid>",
        "email": "<email>",
        "is_verified": <boolean>
    }
    """
    
    class Meta:
        model = User
        fields = ['id', 'email', 'is_verified']
        read_only_fields = ['id', 'is_verified']


class SignupSerializer(serializers.Serializer):
    """
    Serializer for user registration.
    
    Request:
    {
        "email": "<email>",
        "password": "<password>" (min 10 chars, requires uppercase, number, symbol),
        "confirm_password": "<password>"
    }
    """
    
    email = serializers.EmailField(max_length=255)
    password = serializers.CharField(
        write_only=True,
        min_length=10,
        style={'input_type': 'password'}
    )
    confirm_password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'}
    )
    
    def validate_email(self, value):
        """Check email format (duplicate check is done in the view)."""
        return value.lower()
    
    def validate_password(self, value):
        """Validate password against policy requirements."""
        # Minimum length check (10 characters)
        if len(value) < 10:
            raise serializers.ValidationError('Password must be at least 10 characters long.')
        
        # Require uppercase
        if not any(c.isupper() for c in value):
            raise serializers.ValidationError('Password must contain at least one uppercase letter.')
        
        # Require number
        if not any(c.isdigit() for c in value):
            raise serializers.ValidationError('Password must contain at least one number.')
        
        # Require symbol
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in value):
            raise serializers.ValidationError('Password must contain at least one symbol.')
        
        # Also validate against Django's password validators
        try:
            validate_password(value)
        except Exception as e:
            raise serializers.ValidationError(str(e))
        
        return value
    
    def validate(self, attrs):
        """Validate password confirmation match."""
        password = attrs.get('password')
        confirm_password = attrs.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        
        return attrs


class VerifyEmailSerializer(serializers.Serializer):
    """
    Serializer for email verification.
    
    Request:
    {
        "token": "<verification_token>"
    }
    """
    
    token = serializers.CharField(max_length=64)


class ResendVerificationSerializer(serializers.Serializer):
    """
    Serializer for resending verification email.
    
    Request:
    {
        "email": "<email>"
    }
    """
    
    email = serializers.EmailField()


class ForgotPasswordSerializer(serializers.Serializer):
    """
    Serializer for password reset request.
    
    Request:
    {
        "email": "<email>"
    }
    """
    
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    """
    Serializer for password reset confirmation.
    
    Request:
    {
        "token": "<reset_token>",
        "password": "<new_password>" (min 10 chars, requires uppercase, number, symbol)
    }
    """
    
    token = serializers.CharField(max_length=64)
    password = serializers.CharField(
        write_only=True,
        min_length=10,  # Matches password policy requirement
        style={'input_type': 'password'}
    )
    
    def validate_password(self, value):
        """Validate password against policy requirements and Django's password validators."""
        # Minimum length check (10 characters)
        if len(value) < 10:
            raise serializers.ValidationError('Password must be at least 10 characters long.')
        
        # Require uppercase
        if not any(c.isupper() for c in value):
            raise serializers.ValidationError('Password must contain at least one uppercase letter.')
        
        # Require number
        if not any(c.isdigit() for c in value):
            raise serializers.ValidationError('Password must contain at least one number.')
        
        # Require symbol
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in value):
            raise serializers.ValidationError('Password must contain at least one symbol.')
        
        # Also validate against Django's password validators
        validate_password(value)
        return value


class LoginSerializer(serializers.Serializer):
    """
    Serializer for user login.
    
    Request:
    {
        "email": "<email>",
        "password": "<password>"
    }
    
    SECURITY: Uses timing-safe validation to prevent email enumeration.
    When detailed errors are enabled, returns specific error codes.
    """
    
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'}
    )
    
    def __init__(self, *args, **kwargs):
        """Initialize serializer with detailed_errors flag."""
        self.detailed_errors = kwargs.pop('detailed_errors', False)
        super().__init__(*args, **kwargs)
    
    def validate(self, attrs):
        """
        Authenticate the user with timing-safe validation.
        
        Even for non-existent users, we perform password hashing
        to normalize response time and prevent enumeration attacks.
        """
        from django.contrib.auth.hashers import check_password, make_password
        from app.common.exceptions import ErrorCode
        
        email = attrs.get('email', '').lower()
        password = attrs.get('password')
        
        if not email or not password:
            raise serializers.ValidationError('Email and password are required.')
        
        # Try to find the user
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # User doesn't exist - but still perform password hash
            # to normalize timing and prevent enumeration
            make_password(password)
            # Store error code on serializer for view to access
            self.login_error_code = ErrorCode.INVALID_CREDENTIALS
            raise serializers.ValidationError('Invalid credentials.')
        
        # Authenticate using email
        authenticated_user = authenticate(
            request=self.context.get('request'),
            username=email,
            password=password
        )
        
        if not authenticated_user:
            # Store error code - only use detailed code if flag is enabled
            if self.detailed_errors:
                self.login_error_code = ErrorCode.INVALID_PASSWORD
            else:
                self.login_error_code = ErrorCode.INVALID_CREDENTIALS
            raise serializers.ValidationError('Invalid credentials.')
        
        # Check if email is verified (only when detailed errors enabled)
        if self.detailed_errors and not authenticated_user.is_verified:
            self.login_error_code = ErrorCode.EMAIL_NOT_VERIFIED
            raise serializers.ValidationError('Email not verified.')
        
        # Check if account is locked/disabled
        if not authenticated_user.is_active:
            if self.detailed_errors:
                self.login_error_code = ErrorCode.ACCOUNT_LOCKED
            else:
                self.login_error_code = ErrorCode.INVALID_CREDENTIALS
            raise serializers.ValidationError('Invalid credentials.')
        
        attrs['user'] = authenticated_user
        return attrs
