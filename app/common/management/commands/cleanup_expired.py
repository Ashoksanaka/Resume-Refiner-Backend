"""
Django management command to clean up expired resources.

Usage:
    python manage.py cleanup_expired
    python manage.py cleanup_expired --dry-run
    python manage.py cleanup_expired --verbose

This command can be run manually or via cron as an alternative to Celery Beat.
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.authentication.models import IdempotencyKey

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up expired temporary resources (job descriptions, resume requests, tokens)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        now = timezone.now()
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No data will be deleted'))
        
        # Track totals
        totals = {
            'job_descriptions': 0,
            'resume_requests': 0,
            'idempotency_keys': 0,
            'pdfs': 0,
        }
        
        # 1. Clean up expired job descriptions
        jd_queryset = JobDescription.objects.filter(expires_at__lte=now)
        totals['job_descriptions'] = jd_queryset.count()
        
        if verbose and totals['job_descriptions'] > 0:
            for jd in jd_queryset[:10]:  # Show first 10
                self.stdout.write(f"  - JD {jd.id} (expired: {jd.expires_at})")
            if totals['job_descriptions'] > 10:
                self.stdout.write(f"  ... and {totals['job_descriptions'] - 10} more")
        
        if not dry_run and totals['job_descriptions'] > 0:
            jd_queryset.delete()
        
        # 2. Clean up expired resume requests (and their PDFs)
        resume_queryset = ResumeGenerationRequest.objects.filter(expires_at__lte=now)
        totals['resume_requests'] = resume_queryset.count()
        
        if not dry_run:
            import os
            for request in resume_queryset:
                if request.generated_pdf_path:
                    try:
                        if os.path.exists(request.generated_pdf_path):
                            os.remove(request.generated_pdf_path)
                            totals['pdfs'] += 1
                            if verbose:
                                self.stdout.write(f"  - Deleted PDF: {request.generated_pdf_path}")
                    except OSError as e:
                        self.stdout.write(
                            self.style.WARNING(f"  - Failed to delete PDF {request.id}: {e}")
                        )
            
            resume_queryset.delete()
        
        # 3. Clean up expired idempotency keys
        idem_queryset = IdempotencyKey.objects.filter(expires_at__lte=now)
        totals['idempotency_keys'] = idem_queryset.count()
        
        if not dry_run and totals['idempotency_keys'] > 0:
            idem_queryset.delete()
        
        # Report results
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Cleanup Summary:'))
        self.stdout.write(f"  Job Descriptions: {totals['job_descriptions']}")
        self.stdout.write(f"  Resume Requests:  {totals['resume_requests']}")
        self.stdout.write(f"  PDF Files:        {totals['pdfs']}")
        self.stdout.write(f"  Idempotency Keys: {totals['idempotency_keys']}")
        
        total_deleted = sum(totals.values())
        if dry_run:
            self.stdout.write(self.style.WARNING(f'\nWould delete {total_deleted} items'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\nDeleted {total_deleted} items'))
