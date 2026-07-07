"""
AI Agent client for the Resume AI platform.

Handles resume customization via in-process NVIDIA NIM calls.
This client includes strict validation hooks to ensure AI output correctness.

SECURITY:
- All profile data is sanitized before sending to AI
- LaTeX special characters are escaped to prevent injection
"""

import logging
import re
from typing import Optional
from dataclasses import dataclass

from app.common.exceptions import (
    AIServiceException,
    AIServiceQuotaExceededException,
    ModelOutputInvalidException,
)
from app.ai import nim_service

logger = logging.getLogger(__name__)


# LaTeX special characters that need escaping
LATEX_SPECIAL_CHARS = {
    '&': r'\&',
    '%': r'\%',
    '$': r'\$',
    '#': r'\#',
    '_': r'\_',
    '{': r'\{',
    '}': r'\}',
    '~': r'\textasciitilde{}',
    '^': r'\textasciicircum{}',
}


def escape_latex(text: str) -> str:
    """
    Escape LaTeX special characters in user-provided text.

    This prevents LaTeX injection attacks where malicious input
    could execute arbitrary TeX commands.
    """
    if not text:
        return text

    result = text.replace('\\', r'\textbackslash{}')

    for char, replacement in LATEX_SPECIAL_CHARS.items():
        result = result.replace(char, replacement)

    return result


def sanitize_profile_for_latex(data):
    """Recursively escape LaTeX special characters in all string values."""
    if isinstance(data, dict):
        return {k: sanitize_profile_for_latex(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_profile_for_latex(item) for item in data]
    if isinstance(data, str):
        return escape_latex(data)
    return data


# Whitelist of profile fields allowed to be sent to AI
AI_PROFILE_WHITELIST = {
    'personalInfo': {
        'full_name',
        'email',
        'location',
        'portfolio_url',
    },
    'summary': None,
    'experience': None,
    'education': None,
    'skills': None,
    'certifications': None,
    'projects': None,
    'achievements': None,
    'areas_of_interest': None,
    'hobbies': None,
    'volunteering': None,
    'positions': None,
    'career_breaks': None,
    'licenses': None,
    'trainings': None,
    'publications': None,
    'patents': None,
    'honors_awards': None,
    'test_scores': None,
    'languages': None,
    'organizations': None,
    'social_urls': None,
}


def whitelist_profile_for_ai(profile_data: dict) -> dict:
    """Filter profile data to only include whitelisted fields before AI generation."""
    filtered = {}

    for field, allowed_subfields in AI_PROFILE_WHITELIST.items():
        if field not in profile_data:
            continue

        value = profile_data[field]

        if isinstance(allowed_subfields, set):
            if isinstance(value, dict):
                filtered[field] = {
                    k: v for k, v in value.items() if k in allowed_subfields
                }
            else:
                filtered[field] = value
        elif allowed_subfields is None:
            filtered[field] = value

    return filtered


@dataclass
class AIGenerationResult:
    """Result from AI resume generation."""
    latex_source: str
    modifications: list[str]
    raw_response: dict


class AIAgentClient:
    """
    Client for NVIDIA NIM resume customization (in-process).

    The client takes:
    - User profile (structured JSON, filtered to selected sections)
    - Job description (raw text)
    - LaTeX ATS reference template (resume_template.tex)
    - Selected profile section keys

    And returns:
    - Personalized LaTeX based on the fixed ATS template
    - List of modifications made
    """

    async def generate_resume(
        self,
        profile_data: dict,
        job_description_text: str,
        template_content: str,
        template_id: str,
        selected_sections: list[str],
    ) -> AIGenerationResult:
        """Request NVIDIA NIM to customize the resume LaTeX template."""
        logger.info(
            "[AI Agent Client] Called for template: %s, sections: %s",
            template_id,
            selected_sections,
        )
        logger.debug("[AI Agent Client] Input profile keys: %s", list(profile_data.keys()))
        logger.debug(
            "[AI Agent Client] Job description length: %d chars",
            len(job_description_text),
        )
        logger.debug(
            "[AI Agent Client] Template content length: %d chars",
            len(template_content),
        )

        logger.info("[AI Agent Client] Whitelisting profile data (removing sensitive fields)")
        safe_profile_data = whitelist_profile_for_ai(profile_data)
        logger.debug(
            "[AI Agent Client] Whitelisted profile keys: %s",
            list(safe_profile_data.keys()),
        )

        profile_summary = {
            'has_experience': bool(safe_profile_data.get('experience')),
            'experience_count': len(safe_profile_data.get('experience', [])),
            'has_education': bool(safe_profile_data.get('education')),
            'education_count': len(safe_profile_data.get('education', [])),
            'has_skills': bool(safe_profile_data.get('skills')),
            'skills_count': len(safe_profile_data.get('skills', [])),
            'has_projects': bool(safe_profile_data.get('projects')),
            'projects_count': len(safe_profile_data.get('projects', [])),
        }
        logger.info("[AI Agent Client] Parsed user profile summary: %s", profile_summary)

        try:
            logger.info("[AI Agent Client] Calling in-process NVIDIA NIM service")
            result = await nim_service.generate_resume(
                profile=safe_profile_data,
                job_description=job_description_text,
                template=template_content,
                template_id=template_id,
                selected_sections=selected_sections,
            )

            logger.info("[AI Agent Client] Validating AI response structure")
            self._validate_response_structure(result)
            logger.info("[AI Agent Client] Response structure validation passed")

            latex_source = result['latex_source']
            logger.info(
                "[AI Agent Client] Received LaTeX source (length: %d chars)",
                len(latex_source),
            )

            if not latex_source.strip().startswith('\\documentclass'):
                logger.error("[AI Agent Client] AI output does not start with \\documentclass")
                logger.debug("[AI Agent Client] First 100 chars of output: %s", latex_source[:100])
                raise ModelOutputInvalidException(
                    "AI output is not valid LaTeX (must start with \\documentclass)."
                )

            logger.info(
                "[AI Agent Client] LaTeX source validation passed. Modifications: %s",
                result.get('modifications', []),
            )

            return AIGenerationResult(
                latex_source=latex_source,
                modifications=result.get('modifications', []),
                raw_response=result,
            )

        except (AIServiceException, AIServiceQuotaExceededException, ModelOutputInvalidException):
            raise
        except KeyError as e:
            logger.error("AI response missing field: %s", str(e))
            raise ModelOutputInvalidException(f"AI response missing required field: {e}")
        except Exception as e:
            logger.exception("Unexpected error during AI generation: %s", type(e).__name__)
            raise AIServiceException("Resume generation failed due to an internal error") from e

    def _validate_response_structure(self, response: dict) -> None:
        """Validate the basic structure of the AI response."""
        if 'latex_source' not in response:
            raise ModelOutputInvalidException("AI response missing 'latex_source' field")

        if not isinstance(response['latex_source'], str):
            raise ModelOutputInvalidException("'latex_source' must be a string")

        if not response['latex_source'].strip():
            raise ModelOutputInvalidException("'latex_source' cannot be empty")

        if 'modifications' in response:
            if not isinstance(response['modifications'], list):
                raise ModelOutputInvalidException("'modifications' must be a list")


# Singleton instance for convenience
ai_agent_client = AIAgentClient()
