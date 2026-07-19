"""
Pytest configuration and shared fixtures.
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def pytest_configure():
    """Apply lightweight test runtime overrides after Django settings load."""
    from django.conf import settings

    settings.AUTH_PASSWORD_VALIDATORS = []
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
