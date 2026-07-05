"""
LaTeX Service client for the Resume AI platform.

Handles communication with the LaTeX microservice for:
- Template management
- PDF compilation
- Preview retrieval
"""

import os
import uuid
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import httpx
from django.conf import settings
from app.common.exceptions import (
    LatexCompileException,
    LatexServiceException,
    ResourceNotFoundException,
)

logger = logging.getLogger(__name__)


@dataclass
class CompilationResult:
    """Result from LaTeX compilation."""
    pdf_path: str
    compilation_log: str
    success: bool


@dataclass
class TemplateInfo:
    """Template information from LaTeX service."""
    id: str
    name: str
    description: str
    author: str
    version: str
    placeholders: list[str]
    default_filename: str
    has_preview: bool
    preview_generated_at: Optional[str] = None


class LaTeXServiceClient:
    """
    Client for the LaTeX microservice.
    
    The LaTeX service:
    - Manages resume templates
    - Compiles LaTeX source to PDF
    - Generates and serves template previews
    
    CRITICAL RULES:
    - Compilation failure = hard failure
    - No partial or malformed PDFs accepted
    - All errors must be logged and reported
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'LATEX_SERVICE_URL', 'http://localhost:8002')
        self.timeout = getattr(settings, 'LATEX_SERVICE_TIMEOUT', 30)
        self.output_dir = getattr(settings, 'GENERATED_PDF_DIR', Path('/tmp/generated_pdfs'))
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
    
    # =========================================================================
    # Template Management APIs
    # =========================================================================
    
    async def list_templates(self) -> list[TemplateInfo]:
        """
        Get all available templates from the LaTeX service.
        
        Returns:
            List of TemplateInfo objects
        
        Raises:
            LatexServiceException: If service is unavailable
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/templates")
                
                if response.status_code != 200:
                    logger.error("Failed to list templates: %s", response.text)
                    raise LatexServiceException("Failed to fetch templates from LaTeX service")
                
                templates_data = response.json()
                return [TemplateInfo(**t) for t in templates_data]
                
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    async def get_template(self, template_id: str) -> TemplateInfo:
        """
        Get details of a specific template.
        
        Args:
            template_id: ID of the template
        
        Returns:
            TemplateInfo object
        
        Raises:
            ResourceNotFoundException: If template not found
            LatexServiceException: If service is unavailable
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/templates/{template_id}")
                
                if response.status_code == 404:
                    raise ResourceNotFoundException(f"Template '{template_id}' not found")
                
                if response.status_code != 200:
                    logger.error("Failed to get template %s: %s", template_id, response.text)
                    raise LatexServiceException("Failed to fetch template from LaTeX service")
                
                return TemplateInfo(**response.json())
                
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    async def get_template_content(self, template_id: str) -> str:
        """
        Get the raw LaTeX template content.
        
        Args:
            template_id: ID of the template
        
        Returns:
            Template LaTeX source as string
        
        Raises:
            ResourceNotFoundException: If template not found
            LatexServiceException: If service is unavailable
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/templates/{template_id}/content")
                
                if response.status_code == 404:
                    raise ResourceNotFoundException(f"Template '{template_id}' not found")
                
                if response.status_code != 200:
                    logger.error("Failed to get template content %s: %s", template_id, response.text)
                    raise LatexServiceException("Failed to fetch template content from LaTeX service")
                
                return response.text
                
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")

    async def get_resume_template_content(self, template_id: str) -> str:
        """
        Get the ATS reference template (resume_template.tex) for AI customization.

        Args:
            template_id: ID of the template (e.g. 'main')

        Returns:
            Resume template LaTeX source as string
        """
        logger.info(
            "[LaTeX Service Client] Fetching resume template from: %s/templates/%s/resume-template",
            self.base_url,
            template_id,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/templates/{template_id}/resume-template"
                )

                if response.status_code == 404:
                    raise ResourceNotFoundException(
                        f"Resume template for '{template_id}' not found"
                    )

                if response.status_code != 200:
                    logger.error(
                        "Failed to get resume template %s: %s",
                        template_id,
                        response.text,
                    )
                    raise LatexServiceException(
                        "Failed to fetch resume template from LaTeX service"
                    )

                logger.info(
                    "[LaTeX Service Client] Resume template received (length: %d chars)",
                    len(response.text),
                )
                return response.text

        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    async def get_main_template_content(self) -> str:
        """
        Get the main.tex template content.
        
        All resumes are generated from this single template.
        
        Returns:
            Main template LaTeX source as string
        
        Raises:
            LatexServiceException: If service is unavailable or template not found
        """
        logger.info("[LaTeX Service Client] Fetching main template content from: %s/templates/main/content", self.base_url)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/templates/main/content")
                
                if response.status_code != 200:
                    logger.error("[LaTeX Service Client] Failed to get main template content: %s", response.text)
                    raise LatexServiceException("Failed to fetch main template content from LaTeX service")
                
                template_content = response.text
                logger.info("[LaTeX Service Client] Main template content received (length: %d chars)", len(template_content))
                return template_content
                
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    async def get_template_preview_png(self, template_id: str) -> bytes:
        """
        Get the PNG preview of a template.
        
        Args:
            template_id: ID of the template
        
        Returns:
            PNG image bytes
        
        Raises:
            ResourceNotFoundException: If template or preview not found
            LatexServiceException: If service is unavailable
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/templates/{template_id}/preview.png"
                )
                
                if response.status_code == 404:
                    raise ResourceNotFoundException(f"Preview for template '{template_id}' not found")
                
                if response.status_code != 200:
                    logger.error("Failed to get preview for %s: %s", template_id, response.text)
                    raise LatexServiceException("Failed to fetch preview from LaTeX service")
                
                return response.content
                
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    async def get_template_preview_pdf(self, template_id: str) -> bytes:
        """
        Get the PDF preview of a template.
        
        Args:
            template_id: ID of the template
        
        Returns:
            PDF bytes
        
        Raises:
            ResourceNotFoundException: If template or preview not found
            LatexServiceException: If service is unavailable
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/templates/{template_id}/preview.pdf"
                )
                
                if response.status_code == 404:
                    raise ResourceNotFoundException(f"Preview for template '{template_id}' not found")
                
                if response.status_code != 200:
                    logger.error("Failed to get preview for %s: %s", template_id, response.text)
                    raise LatexServiceException("Failed to fetch preview from LaTeX service")
                
                return response.content
                
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    async def generate_template_preview(self, template_id: str) -> dict:
        """
        Generate preview for a template.
        
        Args:
            template_id: ID of the template
        
        Returns:
            Dict with generation result
        
        Raises:
            ResourceNotFoundException: If template not found
            LatexServiceException: If service is unavailable or generation fails
        """
        try:
            async with httpx.AsyncClient(timeout=120) as client:  # Longer timeout for compilation
                response = await client.post(
                    f"{self.base_url}/templates/{template_id}/generate-preview"
                )
                
                if response.status_code == 404:
                    raise ResourceNotFoundException(f"Template '{template_id}' not found")
                
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('detail', {}).get('error', 'Preview generation failed')
                    except Exception:
                        error_msg = f"Preview generation failed with status {response.status_code}"
                    raise LatexServiceException(error_msg)
                
                return response.json()
                
        except httpx.TimeoutException:
            logger.error("Preview generation timed out for template %s", template_id)
            raise LatexServiceException("Preview generation timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    async def reload_templates(self) -> int:
        """
        Trigger template reload on the LaTeX service.
        
        Returns:
            Number of templates loaded
        
        Raises:
            LatexServiceException: If service is unavailable
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/templates/reload")
                
                if response.status_code != 200:
                    logger.error("Failed to reload templates: %s", response.text)
                    raise LatexServiceException("Failed to reload templates")
                
                return response.json().get('templates_loaded', 0)
                
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable")
    
    # =========================================================================
    # Compilation APIs
    # =========================================================================

    async def _compile_via_local_service(
        self,
        latex_source: str,
        output_filename: str,
        template_id: Optional[str] = None,
    ) -> CompilationResult:
        """Compile via the LaTeX microservice (pdflatex + local fix pipeline)."""
        try:
            logger.info(
                "[LaTeX Service Client] Sending compilation request to LaTeX service at: %s/compile",
                self.base_url,
            )
            async with httpx.AsyncClient(timeout=self.timeout * 2) as client:
                response = await client.post(
                    f"{self.base_url}/compile",
                    json={
                        "latex_source": latex_source,
                        "filename": output_filename,
                        "template_id": template_id,
                    },
                )
                logger.info(
                    "[LaTeX Service Client] Received compilation response (status: %d)",
                    response.status_code,
                )

                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_detail = error_data.get('detail', {})
                        if isinstance(error_detail, dict):
                            error_code = error_detail.get('code', 'LATEX_COMPILE_ERROR')
                            compilation_id = error_detail.get('compilation_id')
                            error_msg = error_detail.get('error', 'LaTeX compilation failed')
                            details = error_detail.get('details', {})
                            sample = error_detail.get('sample', '')

                            full_error_msg = error_msg
                            if compilation_id:
                                full_error_msg += f" (Compilation ID: {compilation_id})"
                            if details:
                                if isinstance(details, dict) and 'errors' in details:
                                    error_list = details.get('errors', [])
                                    if error_list:
                                        full_error_msg += f". Errors: {', '.join([e.get('message', '') for e in error_list[:3]])}"

                            raise LatexCompileException(
                                message=full_error_msg,
                                details={
                                    'code': error_code,
                                    'compilation_id': compilation_id,
                                    'details': details,
                                    'sample': sample[:500] if sample else None,
                                },
                                error_code=error_code,
                            )
                        raise LatexCompileException(str(error_detail))
                    except LatexCompileException:
                        raise
                    except Exception:
                        raise LatexCompileException(
                            f"LaTeX compilation failed with status {response.status_code}"
                        )

                pdf_path = Path(self.output_dir) / f"{output_filename}.pdf"
                logger.info("[LaTeX Service Client] Saving PDF to: %s", pdf_path)
                with open(pdf_path, 'wb') as f:
                    f.write(response.content)

                logger.info(
                    "[LaTeX Service Client] LaTeX compilation successful via microservice: %s",
                    pdf_path,
                )
                return CompilationResult(
                    pdf_path=str(pdf_path),
                    compilation_log="Compiled via LaTeX microservice",
                    success=True,
                )

        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out.")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable.")
    
    async def compile_latex(
        self,
        latex_source: str,
        output_filename: Optional[str] = None,
        template_id: Optional[str] = None
    ) -> CompilationResult:
        """
        Compile LaTeX source to PDF.
        
        Args:
            latex_source: The LaTeX source code
            output_filename: Optional filename for the PDF (without extension)
            template_id: Optional template ID to use template assets
        
        Returns:
            CompilationResult with PDF path
        
        Raises:
            LatexCompileException: If compilation fails
            LatexServiceException: If service is unavailable
        """
        if not output_filename:
            output_filename = str(uuid.uuid4())
        
        logger.info("[LaTeX Service Client] LaTeX compilation requested for: %s", output_filename)
        logger.info("[LaTeX Service Client] LaTeX source length: %d chars", len(latex_source))
        logger.debug("[LaTeX Service Client] LaTeX source preview (first 200 chars): %s", latex_source[:200])

        formatex_api_key = getattr(settings, 'FORMATEX_API_KEY', '')
        formatex_fallback = getattr(settings, 'FORMATEX_FALLBACK_TO_LOCAL', True)
        if formatex_api_key:
            from app.latex.ats_preamble import (
                ensure_ats_resume_preamble,
                normalize_document_envelope,
            )
            from app.common.clients.formatex_client import FormaTeXClient

            normalized_source = normalize_document_envelope(
                ensure_ats_resume_preamble(latex_source)
            )
            logger.info(
                "[LaTeX Service Client] Delegating compilation to FormaTeX for: %s",
                output_filename,
            )
            try:
                return await FormaTeXClient().compile(
                    latex_source=normalized_source,
                    output_filename=output_filename,
                )
            except LatexCompileException as exc:
                if not formatex_fallback:
                    raise
                logger.warning(
                    "[LaTeX Service Client] FormaTeX compile failed for %s (%s); falling back to local LaTeX service",
                    output_filename,
                    str(exc),
                )

        return await self._compile_via_local_service(
            latex_source=latex_source,
            output_filename=output_filename,
            template_id=template_id,
        )
    
    async def compile_with_profile(
        self,
        template_id: str,
        profile: dict,
        output_filename: Optional[str] = None
    ) -> CompilationResult:
        """
        Compile a template with profile data substitution.
        
        This is the main method for resume generation.
        
        Args:
            template_id: ID of the template to use
            profile: Profile data to substitute
            output_filename: Optional filename for the PDF
        
        Returns:
            CompilationResult with PDF path
        
        Raises:
            LatexCompileException: If compilation fails
            LatexServiceException: If service is unavailable
            ResourceNotFoundException: If template not found
        """
        if not output_filename:
            output_filename = str(uuid.uuid4())
        
        logger.info("Compiling template %s with profile", template_id)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout * 2) as client:
                response = await client.post(
                    f"{self.base_url}/compile-with-profile",
                    params={"template_id": template_id},
                    json=profile
                )
                
                if response.status_code == 404:
                    raise ResourceNotFoundException(f"Template '{template_id}' not found")
                
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_detail = error_data.get('detail', {})
                        if isinstance(error_detail, dict):
                            error_code = error_detail.get('code', 'LATEX_COMPILE_ERROR')
                            compilation_id = error_detail.get('compilation_id')
                            error_msg = error_detail.get('error', 'LaTeX compilation failed')
                            details = error_detail.get('details', {})
                            sample = error_detail.get('sample', '')
                            
                            # Build detailed error message
                            full_error_msg = error_msg
                            if compilation_id:
                                full_error_msg += f" (Compilation ID: {compilation_id})"
                            if details:
                                if isinstance(details, dict) and 'errors' in details:
                                    error_list = details.get('errors', [])
                                    if error_list:
                                        full_error_msg += f". Errors: {', '.join([e.get('message', '') for e in error_list[:3]])}"
                            
                            # Raise with structured details
                            raise LatexCompileException(
                                message=full_error_msg,
                                details={
                                    'code': error_code,
                                    'compilation_id': compilation_id,
                                    'details': details,
                                    'sample': sample[:500] if sample else None
                                },
                                error_code=error_code
                            )
                        else:
                            error_msg = str(error_detail)
                            raise LatexCompileException(error_msg)
                    except LatexCompileException:
                        raise
                    except Exception:
                        error_msg = f"LaTeX compilation failed with status {response.status_code}"
                        raise LatexCompileException(error_msg)
                
                # Save the PDF
                pdf_path = Path(self.output_dir) / f"{output_filename}.pdf"
                with open(pdf_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info("Template compilation successful: %s", pdf_path)
                
                return CompilationResult(
                    pdf_path=str(pdf_path),
                    compilation_log="Compiled via LaTeX microservice",
                    success=True
                )
            
        except httpx.TimeoutException:
            logger.error("LaTeX service request timed out")
            raise LatexServiceException("LaTeX service timed out.")
        except httpx.HTTPError as e:
            logger.error("LaTeX service HTTP error: %s", str(e))
            raise LatexServiceException("LaTeX service is unavailable.")


# Singleton instance for convenience
latex_service_client = LaTeXServiceClient()
