"""
LaTeX compile and template access for the Resume AI platform.

Templates are loaded from the filesystem (app/latex/templates/).
PDF compilation is delegated to FormaTeX (FORMATEX_API_KEY required).
"""

import os
import uuid
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from app.common.exceptions import (
    LatexCompileException,
    LatexServiceException,
    ResourceNotFoundException,
)
from app.latex import template_store

logger = logging.getLogger(__name__)


@dataclass
class CompilationResult:
    """Result from LaTeX compilation."""
    pdf_path: str
    compilation_log: str
    success: bool


@dataclass
class TemplateInfo:
    """Template information for API and database sync."""
    id: str
    name: str
    description: str
    author: str
    version: str
    placeholders: list[str]
    default_filename: str
    has_preview: bool
    preview_generated_at: Optional[str] = None


def _metadata_to_template_info(metadata: template_store.TemplateMetadata) -> TemplateInfo:
    preview_info = template_store.get_preview_info(metadata.id)
    return TemplateInfo(
        id=metadata.id,
        name=metadata.name,
        description=metadata.description,
        author=metadata.author,
        version=metadata.version,
        placeholders=metadata.placeholders,
        default_filename=metadata.default_filename,
        has_preview=preview_info["has_preview"],
        preview_generated_at=preview_info.get("preview_generated_at"),
    )


class LaTeXServiceClient:
    """
    Template access and FormaTeX PDF compilation.

    CRITICAL RULES:
    - Compilation failure = hard failure
    - No partial or malformed PDFs accepted
    - All errors must be logged and reported
    """

    def __init__(self):
        self.output_dir = getattr(settings, 'GENERATED_PDF_DIR', Path('/tmp/generated_pdfs'))
        os.makedirs(self.output_dir, exist_ok=True)

    async def list_templates(self) -> list[TemplateInfo]:
        templates = template_store.list_templates()
        return [_metadata_to_template_info(t) for t in templates]

    async def get_template(self, template_id: str) -> TemplateInfo:
        metadata = template_store.get_template(template_id)
        if not metadata:
            raise ResourceNotFoundException(f"Template '{template_id}' not found")
        return _metadata_to_template_info(metadata)

    async def get_template_content(self, template_id: str) -> str:
        content = template_store.get_template_content(template_id)
        if content is None:
            raise ResourceNotFoundException(f"Template '{template_id}' not found")
        return content

    async def get_resume_template_content(self, template_id: str) -> str:
        logger.info("[LaTeX Client] Loading resume template from filesystem: %s", template_id)
        content = template_store.get_resume_template_content(template_id)
        if content is None:
            raise ResourceNotFoundException(
                f"Resume template for '{template_id}' not found"
            )
        logger.info("[LaTeX Client] Resume template loaded (length: %d chars)", len(content))
        return content

    async def get_main_template_content(self) -> str:
        content = template_store.get_main_template_content()
        if content is None:
            raise LatexServiceException("Main template not found on filesystem")
        return content

    async def compile_latex(
        self,
        latex_source: str,
        output_filename: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> CompilationResult:
        """
        Compile LaTeX source to PDF via FormaTeX.

        Args:
            latex_source: The LaTeX source code
            output_filename: Optional filename for the PDF (without extension)
            template_id: Unused; kept for call-site compatibility

        Returns:
            CompilationResult with PDF path

        Raises:
            LatexCompileException: If compilation fails
            LatexServiceException: If FormaTeX is not configured
        """
        del template_id  # FormaTeX compiles self-contained documents

        if not output_filename:
            output_filename = str(uuid.uuid4())

        formatex_api_key = getattr(settings, 'FORMATEX_API_KEY', '')
        if not formatex_api_key:
            raise LatexServiceException(
                'FORMATEX_API_KEY is required for PDF compilation'
            )

        from app.latex.ats_preamble import (
            ensure_ats_resume_preamble,
            normalize_document_envelope,
        )
        from app.common.clients.formatex_client import FormaTeXClient

        logger.info("[LaTeX Client] Compiling via FormaTeX: %s", output_filename)
        logger.info("[LaTeX Client] LaTeX source length: %d chars", len(latex_source))

        normalized_source = normalize_document_envelope(
            ensure_ats_resume_preamble(latex_source)
        )

        return await FormaTeXClient().compile(
            latex_source=normalized_source,
            output_filename=output_filename,
        )


# Singleton instance for convenience
latex_service_client = LaTeXServiceClient()
