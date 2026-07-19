"""
Celery tasks for resume generation.

These tasks handle the async processing of resume generation:
1. Load ATS LaTeX template and filtered profile snapshot
2. Call AI agent to customize template for job description + selected sections
3. Validate AI output for hallucinations and section boundaries
4. Compile LaTeX to PDF
5. Update generation request status
"""

import logging
import asyncio
from celery import shared_task
from django.conf import settings
from app.resumes.models import ResumeGenerationRequest
from app.resumes.services import ResumeGenerationService
from app.common.clients import AIAgentClient, LaTeXServiceClient
from app.common.exceptions import (
    ModelOutputInvalidException,
    LatexCompileException,
    AIServiceException,
    AIServiceQuotaExceededException,
    LatexServiceException,
)

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=0,
    time_limit=settings.CELERY_TASK_TIME_LIMIT,
    soft_time_limit=max(settings.CELERY_TASK_TIME_LIMIT - 30, 60),
)
def process_resume_generation(self, generation_id: str):
    """
    Process a resume generation request.

    Loads the fixed LaTeX template, sends filtered profile + selected sections to the
    AI agent for customization, validates output, and compiles to PDF.
    """
    logger.info("[PDF Generation] Starting resume generation process for generation_id: %s", generation_id)

    try:
        generation_request = ResumeGenerationRequest.objects.get(id=generation_id)
        logger.info(
            "[PDF Generation] Generation request found: %s (status: %s)",
            generation_id,
            generation_request.status,
        )
    except ResumeGenerationRequest.DoesNotExist:
        logger.error("[PDF Generation] Generation request not found: %s", generation_id)
        return

    if generation_request.status == ResumeGenerationRequest.STATUS_CANCELLED:
        logger.info("[PDF Generation] Generation request %s was cancelled (skipping)", generation_id)
        return

    if generation_request.status != ResumeGenerationRequest.STATUS_PENDING:
        logger.warning(
            "[PDF Generation] Generation request %s already in status: %s (skipping)",
            generation_id,
            generation_request.status,
        )
        return

    generation_request.mark_processing()

    try:
        latex_client = LaTeXServiceClient()
        template_id = generation_request.template_id

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.info(
                "[PDF Generation] Fetching resume template content for template_id: %s",
                template_id,
            )
            template_content = loop.run_until_complete(
                latex_client.get_resume_template_content(template_id)
            )
            logger.info(
                "[PDF Generation] Resume template content received (length: %d chars)",
                len(template_content),
            )
        finally:
            loop.close()

        generation_request.refresh_from_db()
        if generation_request.status == ResumeGenerationRequest.STATUS_CANCELLED:
            logger.info("[PDF Generation] Generation cancelled before AI call: %s", generation_id)
            return

        ai_client = AIAgentClient()
        selected_sections = generation_request.selected_sections or []

        profile_snapshot = generation_request.profile_snapshot
        profile_summary = {
            'selected_sections': selected_sections,
            'profile_keys': list(profile_snapshot.keys()),
        }
        logger.info("[PDF Generation] Sending to AI agent: %s", profile_summary)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ai_result = loop.run_until_complete(
                ai_client.generate_resume(
                    profile_data=profile_snapshot,
                    job_description_text=generation_request.job_description.text,
                    template_content=template_content,
                    template_id=template_id,
                    selected_sections=selected_sections,
                )
            )
            logger.info(
                "[PDF Generation] AI agent response received. LaTeX source length: %d chars",
                len(ai_result.latex_source),
            )
        finally:
            loop.close()

        latex_source = ai_result.latex_source
        modifications = ai_result.modifications

        ResumeGenerationService.validate_ai_output(
            generation_request,
            latex_source,
            modifications,
        )

        generation_request.refresh_from_db()
        if generation_request.status == ResumeGenerationRequest.STATUS_CANCELLED:
            logger.info("[PDF Generation] Generation cancelled before LaTeX compile: %s", generation_id)
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            compile_result = loop.run_until_complete(
                latex_client.compile_latex(
                    latex_source=latex_source,
                    output_filename=str(generation_request.id),
                    template_id=template_id,
                )
            )
            logger.info(
                "[PDF Generation] LaTeX compilation successful. PDF saved at: %s",
                compile_result.pdf_path,
            )
        finally:
            loop.close()

        generation_request.refresh_from_db()
        if generation_request.status == ResumeGenerationRequest.STATUS_CANCELLED:
            logger.info(
                "[PDF Generation] Generation cancelled after compile (not overwriting): %s",
                generation_id,
            )
            return

        generation_request.mark_success(
            latex_source=latex_source,
            pdf_path=compile_result.pdf_path,
            modifications=modifications,
        )
        logger.info("[PDF Generation] Resume generation completed successfully: %s", generation_id)

    except ModelOutputInvalidException as e:
        logger.error("AI output validation failed for %s: %s", generation_id, str(e))
        generation_request.mark_failed(
            error_code='MODEL_OUTPUT_INVALID',
            error_details=str(e),
        )

    except LatexCompileException as e:
        logger.error("LaTeX compilation failed for %s: %s", generation_id, str(e))
        generation_request.mark_failed(
            error_code='LATEX_COMPILE_ERROR',
            error_details=str(e),
        )

    except AIServiceQuotaExceededException as e:
        logger.error("AI service quota exceeded for %s: %s", generation_id, str(e))
        generation_request.mark_failed(
            error_code='AI_SERVICE_QUOTA_EXCEEDED',
            error_details=str(e),
        )
    except AIServiceException as e:
        logger.error("AI service error for %s: %s", generation_id, str(e))
        generation_request.mark_failed(
            error_code='AI_SERVICE_ERROR',
            error_details=str(e),
        )

    except LatexServiceException as e:
        logger.error("LaTeX service error for %s: %s", generation_id, str(e))
        generation_request.mark_failed(
            error_code='LATEX_SERVICE_ERROR',
            error_details=str(e),
        )

    except Exception as e:
        logger.exception(
            "Unexpected error processing generation %s: %s",
            generation_id,
            type(e).__name__,
        )
        generation_request.mark_failed(
            error_code='INTERNAL_SERVER_ERROR',
            error_details='An unexpected error occurred.',
        )
