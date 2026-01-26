"""
Pytest configuration and shared fixtures.
"""

import os
import django
from django.conf import settings

# Configure Django settings for pytest
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def pytest_configure():
    """Configure pytest with Django settings."""
    # Override database for testing
    settings.DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
    
    # Disable password validators for faster testing
    settings.AUTH_PASSWORD_VALIDATORS = []
    
    # Use console email backend
    settings.EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    
    # Disable celery task execution in tests
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    
    django.setup()
