"""
Django settings for Resume AI Platform.

This configuration is designed for a production-ready MVP with:
- PostgreSQL database
- Redis for task queue (Celery)
- DRF for API endpoints
- Custom user model with email authentication
- 24-hour TTL for temporary resources
"""

import os
from pathlib import Path
from datetime import timedelta

from decouple import config, Csv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# SECURITY SETTINGS
# =============================================================================

SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key-change-in-production')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())


# =============================================================================
# APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'rest_framework',
    'corsheaders',
    'django_celery_beat',
    'django_celery_results',
    
    # Local apps
    'app.authentication',
    'app.common',
    'app.profiles',
    'app.resumes',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# =============================================================================
# DATABASE
# =============================================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('POSTGRES_DB', default='resumeai'),
        'USER': config('POSTGRES_USER', default='resumeai'),
        'PASSWORD': config('POSTGRES_PASSWORD', default='resumeai'),
        'HOST': config('POSTGRES_HOST', default='localhost'),
        'PORT': config('POSTGRES_PORT', default='5432'),
    }
}


# =============================================================================
# AUTHENTICATION
# =============================================================================

AUTH_USER_MODEL = 'authentication.User'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 10},  # Matches password policy requirement
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Session settings for cookie-based auth
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = 'sessionid'
SESSION_COOKIE_AGE = 86400  # 24 hours
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to cookies

# Cookie security configuration - environment-aware
# In production: Secure=True, SameSite=None (for cross-site requests)
# In development: Secure=False, SameSite=Lax (for localhost)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=not DEBUG, cast=bool)
SESSION_COOKIE_SAMESITE = config('SESSION_COOKIE_SAMESITE', default='Lax' if DEBUG else 'Lax')

# Security validation: When SameSite=None, Secure MUST be True (browser requirement)
if SESSION_COOKIE_SAMESITE == 'None' and not SESSION_COOKIE_SECURE:
    raise ValueError(
        "SESSION_COOKIE_SECURE must be True when SESSION_COOKIE_SAMESITE is 'None'. "
        "Browsers reject cookies with SameSite=None without Secure flag."
    )


# =============================================================================
# DJANGO REST FRAMEWORK
# =============================================================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'app.authentication.backends.CsrfExemptSessionAuthentication',
        'app.authentication.backends.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '5000/hour',  # Increased to support status polling
        'resume_generation': '20/hour',  # Rate for AI generation calls
        'status_check': '600/minute',  # High rate for status polling
    },
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'EXCEPTION_HANDLER': 'app.common.exceptions.custom_exception_handler',
    'NON_FIELD_ERRORS_KEY': 'non_field_errors',
}


# =============================================================================
# CORS SETTINGS
# =============================================================================

CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000',
    cast=Csv()
)
CORS_ALLOW_CREDENTIALS = True
# Expose headers needed for file downloads
CORS_EXPOSE_HEADERS = [
    'Content-Disposition',
    'Content-Type',
    'Content-Length',
]
# Allow all headers from frontend
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'idempotency-key',
]

CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000',
    cast=Csv()
)

# In development, CSRF cookies don't need HTTPS
CSRF_COOKIE_SAMESITE = 'Lax' if DEBUG else 'None'
CSRF_COOKIE_SECURE = not DEBUG


# =============================================================================
# CELERY CONFIGURATION
# =============================================================================

CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_CACHE_BACKEND = 'default'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = config('CELERY_TASK_TIME_LIMIT', default=300, cast=int)  # 5 minutes max per task
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'


# =============================================================================
# APPLICATION-SPECIFIC SETTINGS
# =============================================================================

# TTL for temporary resources (job descriptions, resumes)
DATA_TTL_HOURS = config('DATA_TTL_HOURS', default=24, cast=int)

# AI Agent configuration
AI_AGENT_URL = config('AI_AGENT_URL', default='http://localhost:8001')
AI_AGENT_TIMEOUT = config('AI_AGENT_TIMEOUT', default=180, cast=int)  # Increased for Gemini API latency (120s) + processing overhead

# LaTeX microservice configuration
LATEX_SERVICE_URL = config('LATEX_SERVICE_URL', default='http://localhost:8002')
LATEX_SERVICE_TIMEOUT = config('LATEX_SERVICE_TIMEOUT', default=30, cast=int)

# Resume templates directory
TEMPLATES_DIR = BASE_DIR / 'templates' / 'resumes'

# Generated PDFs temporary storage
GENERATED_PDF_DIR = BASE_DIR / 'generated' / 'pdfs'

# Email verification token expiry
EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS = config('EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS', default=24, cast=int)


# =============================================================================
# EMAIL CONFIGURATION (SendGrid)
# =============================================================================

# SendGrid API Key (preferred method)
# Get your API key from https://app.sendgrid.com/settings/api_keys
SENDGRID_API_KEY = config('SENDGRID_API_KEY', default='')

# Email settings
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@resume-ai.com')
EMAIL_FROM_NAME = config('EMAIL_FROM_NAME', default='Resume AI')

# Frontend URL for email links (verification, password reset)
FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:3000')

# Fallback to Django email backend if SendGrid is not configured
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = config('EMAIL_HOST', default='localhost')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')


# =============================================================================
# INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# =============================================================================
# STATIC FILES
# =============================================================================

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'


# =============================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =============================================================================
# REQUEST SIZE LIMITS (Security)
# =============================================================================

# Maximum size of a request body (5MB - sufficient for profile + JD)
DATA_UPLOAD_MAX_MEMORY_SIZE = config('DATA_UPLOAD_MAX_MEMORY_SIZE', default=5 * 1024 * 1024, cast=int)  # 5MB

# Maximum number of form fields (defense against DoS)
DATA_UPLOAD_MAX_NUMBER_FIELDS = config('DATA_UPLOAD_MAX_NUMBER_FIELDS', default=1000, cast=int)


# =============================================================================
# LOGGING CONFIGURATION
# IMPORTANT: Do not log PII (profile data, job descriptions)
# =============================================================================

import logging
import re


class PIIFilter(logging.Filter):
    """
    Filter to redact PII (Personally Identifiable Information) from log records.
    
    Prevents logging of:
    - Email addresses
    - Phone numbers
    - SSNs
    - Other sensitive patterns
    """
    # Patterns to match and redact
    PII_PATTERNS = [
        # Email addresses
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[REDACTED_EMAIL]'),
        # Phone numbers (various formats)
        (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[REDACTED_PHONE]'),
        (r'\b\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[REDACTED_PHONE]'),
        # SSNs
        (r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED_SSN]'),
        # Long numeric sequences (potential credit cards, account numbers)
        (r'\b\d{13,}\b', '[REDACTED_NUMBER]'),
    ]
    
    def filter(self, record):
        """
        Filter log record by redacting PII patterns.
        
        Args:
            record: LogRecord instance
            
        Returns:
            True (always allows the record, but modifies it)
        """
        # Get the message
        message = str(record.getMessage())
        
        # Apply all PII patterns
        for pattern, replacement in self.PII_PATTERNS:
            message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
        
        # Update the record
        record.msg = message
        record.args = ()  # Clear args since we've formatted the message
        
        return True


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'filters': {
        'pii_filter': {
            '()': PIIFilter,
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'filters': ['pii_filter'],  # Apply PII filtering to all console logs
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'app': {
            'handlers': ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
