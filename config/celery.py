"""
Celery configuration for the Resume AI platform.

Handles async task processing for:
- Resume generation (AI agent + LaTeX compilation)
- TTL cleanup (deleting expired resources)
"""

import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('resumeai')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


# =============================================================================
# PERIODIC TASKS (Celery Beat)
# =============================================================================

app.conf.beat_schedule = {
    # Clean up expired resources every hour
    'cleanup-expired-resources': {
        'task': 'app.common.tasks.cleanup_expired_resources',
        'schedule': crontab(minute=0),  # Every hour at minute 0
    },
    # Clean up orphan PDF files daily
    'cleanup-orphan-pdfs': {
        'task': 'app.common.tasks.cleanup_orphan_pdfs',
        'schedule': crontab(hour=3, minute=0),  # Daily at 3:00 AM
    },
    # Clean up expired idempotency keys daily
    'cleanup-expired-idempotency-keys': {
        'task': 'app.authentication.tasks.cleanup_expired_idempotency_keys',
        'schedule': crontab(hour=4, minute=0),  # Daily at 4:00 AM
    },
}


# =============================================================================
# TASK ROUTES
# =============================================================================

app.conf.task_routes = {
    # Resume generation tasks need more time
    'app.resumes.tasks.*': {'queue': 'resume_generation'},
    # Cleanup tasks
    'app.common.tasks.*': {'queue': 'maintenance'},
    'app.authentication.tasks.*': {'queue': 'maintenance'},
}
