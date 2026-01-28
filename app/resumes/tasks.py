"""
Celery tasks for resume generation.

These tasks handle the async processing of resume generation:
1. Get profile snapshot and job description
2. Call AI agent for LaTeX generation (AI generates complete LaTeX from scratch)
3. Validate AI output for hallucinations
4. Compile LaTeX to PDF
5. Update generation request status

NOTE: Templates are no longer used - the AI generates complete LaTeX documents from scratch.
"""

import logging
import asyncio
from pathlib import Path
from celery import shared_task
from django.conf import settings
from app.resumes.models import ResumeGenerationRequest
from app.resumes.services import ResumeGenerationService
# HallucinationDetector temporarily disabled - can be re-enabled if needed
from app.common.models import Template
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
    max_retries=0,  # No retries - failures are hard failures
    time_limit=300,  # 5 minute timeout
    soft_time_limit=270,  # 4.5 minute soft timeout
)
def process_resume_generation(self, generation_id: str):
    """
    Process a resume generation request.
    
    This task:
    1. Marks the request as processing
    2. Calls the AI agent
    3. Validates the AI output
    4. Compiles LaTeX to PDF
    5. Updates the request status
    
    CRITICAL RULES:
    - Any failure = hard failure (no silent fixes)
    - Hallucinations cause failure
    - LaTeX compile errors cause failure
    - All errors are logged with request ID (no PII)
    """
    logger.info("[PDF Generation] Starting resume generation process for generation_id: %s", generation_id)
    
    try:
        # Get the generation request
        logger.debug("[PDF Generation] Fetching generation request from database: %s", generation_id)
        generation_request = ResumeGenerationRequest.objects.get(id=generation_id)
        logger.info("[PDF Generation] Generation request found: %s (status: %s)", generation_id, generation_request.status)
    except ResumeGenerationRequest.DoesNotExist:
        logger.error("[PDF Generation] Generation request not found: %s", generation_id)
        return
    
    # Check if already processed (idempotency)
    if generation_request.status != ResumeGenerationRequest.STATUS_PENDING:
        logger.warning(
            "[PDF Generation] Generation request %s already in status: %s (skipping)",
            generation_id, generation_request.status
        )
        return
    
    # Mark as processing
    logger.info("[PDF Generation] Marking generation request as processing: %s", generation_id)
    generation_request.mark_processing()
    
    try:
        # NOTE: Template fetching is deprecated - AI now generates LaTeX from scratch
        # Template content is still fetched and passed for backward compatibility but is ignored by the AI agent
        logger.info("[PDF Generation] Initializing LaTeX service client")
        latex_client = LaTeXServiceClient()
        
        # Run async code in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Get template content (deprecated - kept for backward compatibility)
            # The AI agent no longer uses templates - it generates complete LaTeX from scratch
            logger.info("[PDF Generation] Fetching template content (deprecated - kept for API compatibility)")
            template_content = loop.run_until_complete(
                latex_client.get_main_template_content()
            )
            logger.info("[PDF Generation] Template content received (length: %d chars) - NOTE: Not used by AI", len(template_content))
        finally:
            loop.close()
        
        # Call AI agent
        logger.info("[PDF Generation] Initializing AI agent client")
        ai_client = AIAgentClient()
        
        # Log profile data summary (without PII)
        profile_snapshot = generation_request.profile_snapshot
        profile_summary = {
            'has_experience': bool(profile_snapshot.get('experience')),
            'experience_count': len(profile_snapshot.get('experience', [])),
            'has_education': bool(profile_snapshot.get('education')),
            'education_count': len(profile_snapshot.get('education', [])),
            'has_skills': bool(profile_snapshot.get('skills')),
            'skills_count': len(profile_snapshot.get('skills', [])),
            'has_projects': bool(profile_snapshot.get('projects')),
            'projects_count': len(profile_snapshot.get('projects', [])),
        }
        logger.info("[PDF Generation] Sending user profile to AI agent. Profile summary: %s", profile_summary)
        logger.debug("[PDF Generation] Job description length: %d chars", len(generation_request.job_description.text))
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            logger.info("[PDF Generation] Calling AI agent to generate complete LaTeX document")
            ai_result = loop.run_until_complete(
                ai_client.generate_resume(
                    profile_data=generation_request.profile_snapshot,
                    job_description_text=generation_request.job_description.text,
                    template_content=template_content,  # Deprecated - ignored by AI agent
                    template_id='main',  # Used for logging/identification only
                )
            )
            logger.info("[PDF Generation] AI agent response received. LaTeX source length: %d chars", len(ai_result.latex_source))
            logger.info("[PDF Generation] AI agent modifications: %s", ai_result.modifications)
        finally:
            loop.close()
        
        latex_source = ai_result.latex_source
        modifications = ai_result.modifications
        
        # Validate AI output for hallucinations
        logger.info("[PDF Generation] Validating AI output for hallucinations and content integrity")
        ResumeGenerationService.validate_ai_output(
            generation_request,
            latex_source,
            modifications
        )
        logger.info("[PDF Generation] AI output validation passed")
        
        # Compile LaTeX to PDF using LaTeX service
        logger.info("[PDF Generation] Compiling LaTeX source to PDF (output filename: %s)", str(generation_request.id))
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            compile_result = loop.run_until_complete(
                latex_client.compile_latex(
                    latex_source=latex_source,
                    output_filename=str(generation_request.id),
                    template_id=None,  # No template-specific assets needed for main.tex
                )
            )
            logger.info("[PDF Generation] LaTeX compilation successful. PDF saved at: %s", compile_result.pdf_path)
        finally:
            loop.close()
        
        # Mark as success
        logger.info("[PDF Generation] Marking generation request as successful: %s", generation_id)
        generation_request.mark_success(
            latex_source=latex_source,
            pdf_path=compile_result.pdf_path,
            modifications=modifications,
        )
        
        logger.info("[PDF Generation] Resume generation completed successfully: %s", generation_id)
        
    except ModelOutputInvalidException as e:
        logger.error(
            "AI output validation failed for %s: %s",
            generation_id, str(e)
        )
        generation_request.mark_failed(
            error_code='MODEL_OUTPUT_INVALID',
            error_details=str(e)
        )
        
    except LatexCompileException as e:
        logger.error(
            "LaTeX compilation failed for %s: %s",
            generation_id, str(e)
        )
        generation_request.mark_failed(
            error_code='LATEX_COMPILE_ERROR',
            error_details=str(e)
        )
        
    except AIServiceQuotaExceededException as e:
        logger.error(
            "AI service quota exceeded for %s: %s",
            generation_id, str(e)
        )
        generation_request.mark_failed(
            error_code='AI_SERVICE_QUOTA_EXCEEDED',
            error_details=str(e)
        )
    except AIServiceException as e:
        logger.error(
            "AI service error for %s: %s",
            generation_id, str(e)
        )
        generation_request.mark_failed(
            error_code='AI_SERVICE_ERROR',
            error_details=str(e)
        )
        
    except LatexServiceException as e:
        logger.error(
            "LaTeX service error for %s: %s",
            generation_id, str(e)
        )
        generation_request.mark_failed(
            error_code='LATEX_SERVICE_ERROR',
            error_details=str(e)
        )
        
    except Exception as e:
        logger.exception(
            "Unexpected error processing generation %s: %s",
            generation_id, type(e).__name__
        )
        generation_request.mark_failed(
            error_code='INTERNAL_SERVER_ERROR',
            error_details='An unexpected error occurred.'
        )


def get_default_template() -> str:
    """
    Return a default LaTeX template for development.
    
    This is used when no template file is found.
    """
    return r"""
\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[margin=1in]{geometry}
\usepackage{hyperref}
\usepackage{enumitem}

% Customize sections
\usepackage{titlesec}
\titleformat{\section}{\large\bfseries}{\thesection}{1em}{}[\titlerule]
\titleformat{\subsection}{\bfseries}{\thesubsection}{1em}{}

\begin{document}

% PLACEHOLDER - AI will customize this template

\end{document}
"""
