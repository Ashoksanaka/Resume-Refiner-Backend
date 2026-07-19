"""
FormaTeX API client for LaTeX-to-PDF compilation.

Replaces local pdflatex when FORMATEX_API_KEY is configured.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from django.conf import settings

from app.common.clients.latex_service import CompilationResult
from app.common.exceptions import LatexCompileException, LatexServiceException

logger = logging.getLogger(__name__)


class FormaTeXClient:
    """HTTP client for the FormaTeX compile API."""

    def __init__(self):
        self.api_key = getattr(settings, 'FORMATEX_API_KEY', '')
        self.base_url = (getattr(settings, 'FORMATEX_API_BASE_URL', '') or '').rstrip('/')
        if not self.base_url:
            raise LatexServiceException('FORMATEX_API_BASE_URL is not configured.')
        self.engine = getattr(settings, 'FORMATEX_ENGINE', 'auto')
        self.timeout = getattr(settings, 'FORMATEX_TIMEOUT', 120)
        self.use_smart_compile = getattr(settings, 'FORMATEX_USE_SMART_COMPILE', True)
        self.output_dir = getattr(settings, 'GENERATED_PDF_DIR', Path('/tmp/generated_pdfs'))
        os.makedirs(self.output_dir, exist_ok=True)

    def _compile_endpoint(self) -> str:
        path = '/compile/smart' if self.use_smart_compile else '/compile'
        return f"{self.base_url}{path}"

    async def compile(
        self,
        latex_source: str,
        output_filename: str,
        engine: Optional[str] = None,
    ) -> CompilationResult:
        """
        Compile LaTeX source to PDF via FormaTeX.

        Args:
            latex_source: LaTeX document source
            output_filename: Output PDF basename (without .pdf extension)
            engine: Optional engine override (auto, xelatex, pdflatex)

        Returns:
            CompilationResult with path to saved PDF

        Raises:
            LatexCompileException: On 422 compile failure
            LatexServiceException: On auth, quota, network, or server errors
        """
        if not self.api_key:
            raise LatexServiceException('FormaTeX API key is not configured.')

        endpoint = self._compile_endpoint()
        compile_engine = engine or self.engine

        logger.info(
            "[FormaTeX Client] Compiling %s via %s (engine=%s, %d chars)",
            output_filename,
            endpoint,
            compile_engine,
            len(latex_source),
        )

        headers = {
            'X-API-Key': self.api_key,
            'Content-Type': 'application/json',
        }
        payload = {
            'latex': latex_source,
            'engine': compile_engine,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)

            if response.status_code == 200:
                pdf_path = Path(self.output_dir) / f"{output_filename}.pdf"
                with open(pdf_path, 'wb') as pdf_file:
                    pdf_file.write(response.content)

                logger.info(
                    "[FormaTeX Client] Compilation successful: %s (%d bytes)",
                    pdf_path,
                    len(response.content),
                )
                return CompilationResult(
                    pdf_path=str(pdf_path),
                    compilation_log='Compiled via FormaTeX',
                    success=True,
                )

            if response.status_code == 422:
                error_msg = 'LaTeX compilation failed'
                compiler_log = ''
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                    compiler_log = error_data.get('log', '') or error_data.get('compiler_log', '')
                except Exception:
                    error_msg = response.text or error_msg

                if compiler_log:
                    logger.error(
                        "[FormaTeX Client] Compile log for %s:\n%s",
                        output_filename,
                        compiler_log[:3000],
                    )

                details = {'compilation_id': output_filename}
                if compiler_log:
                    details['compiler_log'] = compiler_log[:5000]

                raise LatexCompileException(
                    message=error_msg,
                    details=details,
                )

            if response.status_code == 401:
                raise LatexServiceException(
                    'FormaTeX authentication failed. Check FORMATEX_API_KEY.'
                )

            if response.status_code == 429:
                raise LatexServiceException(
                    'FormaTeX API quota exceeded. Upgrade your plan or wait for quota reset.'
                )

            logger.error(
                "[FormaTeX Client] Unexpected response %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise LatexServiceException(
                f'FormaTeX compilation failed with status {response.status_code}'
            )

        except httpx.TimeoutException:
            logger.error("[FormaTeX Client] Request timed out after %ss", self.timeout)
            raise LatexServiceException('FormaTeX compilation timed out.')
        except httpx.HTTPError as exc:
            logger.error("[FormaTeX Client] HTTP error: %s", exc)
            raise LatexServiceException('FormaTeX service is unavailable.')
        except (LatexCompileException, LatexServiceException):
            raise
