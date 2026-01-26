"""
Common Celery tasks for the Resume AI platform.

Handles periodic maintenance tasks:
- TTL cleanup for expired resources
"""

import logging
from celery import shared_task
from django.utils import timezone
from app.resumes.models import JobDescription, ResumeGenerationRequest

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_resources():
    """
    Delete all expired temporary resources.
    
    This task runs hourly via Celery Beat.
    
    Resources with TTL:
    - JobDescription (24 hours)
    - ResumeGenerationRequest (24 hours)
    
    Also cleans up:
    - Associated PDF files for expired resume requests
    """
    now = timezone.now()
    
    # Delete expired job descriptions
    # This will cascade delete associated resume requests
    jd_count = JobDescription.objects.filter(expires_at__lte=now).count()
    if jd_count > 0:
        JobDescription.objects.filter(expires_at__lte=now).delete()
        logger.info("Deleted %d expired job descriptions", jd_count)
    
    # Delete expired resume generation requests
    # (Some may exist without a JD due to cascade timing)
    resume_requests = ResumeGenerationRequest.objects.filter(expires_at__lte=now)
    resume_count = resume_requests.count()
    
    if resume_count > 0:
        # Clean up PDF files first
        for request in resume_requests:
            if request.generated_pdf_path:
                try:
                    import os
                    if os.path.exists(request.generated_pdf_path):
                        os.remove(request.generated_pdf_path)
                        logger.debug("Deleted PDF: %s", request.id)
                except OSError as e:
                    logger.warning("Failed to delete PDF for %s: %s", request.id, str(e))
        
        # Delete the database records
        resume_requests.delete()
        logger.info("Deleted %d expired resume generation requests", resume_count)
    
    return {
        'job_descriptions_deleted': jd_count,
        'resume_requests_deleted': resume_count,
    }


@shared_task
def cleanup_orphan_pdfs():
    """
    Clean up orphan PDF files that don't have corresponding database records.
    
    This is a safety net for any PDFs left behind due to errors.
    Runs daily.
    """
    import os
    from pathlib import Path
    from django.conf import settings
    
    pdf_dir = Path(getattr(settings, 'GENERATED_PDF_DIR', '/tmp/generated_pdfs'))
    
    if not pdf_dir.exists():
        return {'orphan_pdfs_deleted': 0}
    
    orphan_count = 0
    
    for pdf_file in pdf_dir.glob('*.pdf'):
        # Extract UUID from filename
        try:
            file_uuid = pdf_file.stem
            # Check if a resume request exists with this ID
            if not ResumeGenerationRequest.objects.filter(id=file_uuid).exists():
                pdf_file.unlink()
                orphan_count += 1
                logger.debug("Deleted orphan PDF: %s", pdf_file.name)
        except Exception as e:
            logger.warning("Error processing PDF %s: %s", pdf_file.name, str(e))
    
    if orphan_count > 0:
        logger.info("Deleted %d orphan PDF files", orphan_count)
    
    return {'orphan_pdfs_deleted': orphan_count}
