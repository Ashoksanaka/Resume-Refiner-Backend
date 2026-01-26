"""
Celery tasks for resume generation.

These tasks handle the async processing of resume generation:
1. Get profile snapshot and job description
2. Call AI agent for LaTeX generation
3. Validate AI output for hallucinations
4. Compile LaTeX to PDF
5. Update generation request status
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
    logger.info("Starting resume generation: %s", generation_id)
    
    try:
        # Get the generation request
        generation_request = ResumeGenerationRequest.objects.get(id=generation_id)
    except ResumeGenerationRequest.DoesNotExist:
        logger.error("Generation request not found: %s", generation_id)
        return
    
    # Check if already processed (idempotency)
    if generation_request.status != ResumeGenerationRequest.STATUS_PENDING:
        logger.warning(
            "Generation request %s already in status: %s",
            generation_id, generation_request.status
        )
        return
    
    # Mark as processing
    generation_request.mark_processing()
    
    try:
        # Get main template content from LaTeX service
        # All resumes are generated from main.tex
        latex_client = LaTeXServiceClient()
        
        # Run async code in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Get main template content from LaTeX service
            template_content = loop.run_until_complete(
                latex_client.get_main_template_content()
            )
        finally:
            loop.close()
        
        # Call AI agent
        ai_client = AIAgentClient()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            ai_result = loop.run_until_complete(
                ai_client.generate_resume(
                    profile_data=generation_request.profile_snapshot,
                    job_description_text=generation_request.job_description.text,
                    template_content=template_content,
                    template_id='main',  # Use 'main' as template identifier
                )
            )
        finally:
            loop.close()
        
        latex_source = ai_result.latex_source
        modifications = ai_result.modifications
        
        # Validate AI output for hallucinations
        ResumeGenerationService.validate_ai_output(
            generation_request,
            latex_source,
            modifications
        )
        
        # Compile LaTeX to PDF using LaTeX service
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
        finally:
            loop.close()
        
        # Mark as success
        generation_request.mark_success(
            latex_source=latex_source,
            pdf_path=compile_result.pdf_path,
            modifications=modifications,
        )
        
        logger.info("Resume generation completed: %s", generation_id)
        
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
