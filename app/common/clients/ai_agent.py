"""
AI Agent client for the Resume AI platform.

Handles communication with the AI agent service for resume customization.
This client includes strict validation hooks to ensure AI output correctness.

SECURITY:
- All profile data is sanitized before sending to AI
- LaTeX special characters are escaped to prevent injection
"""

import logging
import re
from typing import Optional
from dataclasses import dataclass
import httpx
from django.conf import settings
from app.common.exceptions import (
    AIServiceException,
    AIServiceQuotaExceededException,
    ModelOutputInvalidException,
)

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
    
    # First escape backslashes
    result = text.replace('\\', r'\textbackslash{}')
    
    for char, replacement in LATEX_SPECIAL_CHARS.items():
        result = result.replace(char, replacement)
    
    return result


def sanitize_profile_for_latex(data):
    """
    Recursively escape LaTeX special characters in all string values.
    """
    if isinstance(data, dict):
        return {k: sanitize_profile_for_latex(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_profile_for_latex(item) for item in data]
    elif isinstance(data, str):
        return escape_latex(data)
    else:
        return data


# Whitelist of profile fields allowed to be sent to AI agent
# SECURITY: Only fields explicitly whitelisted are sent to prevent data leakage
# Dict fields have sets of allowed subfields, simple fields have None
AI_PROFILE_WHITELIST = {
    'personalInfo': {
        'full_name',
        'email',
        'location',  # General location only, not full address
        'portfolio_url'
    },
    'summary': None,  # Simple field - include as-is
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
    'social_urls': None  # URLs are safe for AI
    # EXCLUDED: address (too sensitive), contact_info (sensitive), profile_picture.url (not needed)
}


def whitelist_profile_for_ai(profile_data: dict) -> dict:
    """
    Filter profile data to only include whitelisted fields before sending to AI agent.
    
    SECURITY: This function ensures that sensitive fields like contact_info,
    profile_picture.url, and full address details are never sent to the AI agent.
    
    Args:
        profile_data: Full profile data dictionary
        
    Returns:
        Filtered profile data with only whitelisted fields
    """
    filtered = {}
    
    # Handle top-level fields
    for field, allowed_subfields in AI_PROFILE_WHITELIST.items():
        if field not in profile_data:
            continue
        
        value = profile_data[field]
        
        if isinstance(allowed_subfields, set):
            # This is a dict field (like personalInfo) - filter subfields
            if isinstance(value, dict):
                filtered[field] = {
                    k: v for k, v in value.items() if k in allowed_subfields
                }
            else:
                # Not a dict, include as-is if whitelisted
                filtered[field] = value
        elif allowed_subfields is None:
            # This is a simple field (like summary, skills) - include as-is
            filtered[field] = value
    
    return filtered


@dataclass
class AIGenerationResult:
    """Result from AI agent generation."""
    latex_source: str
    modifications: list[str]
    raw_response: dict


class AIAgentClient:
    """
    Client for the AI Agent microservice.
    
    The AI agent takes:
    - User profile (structured JSON)
    - Job description (raw text)
    - LaTeX template (deprecated - no longer used, kept for backward compatibility)
    
    And returns:
    - Complete LaTeX source (generated from scratch)
    - List of modifications made
    
    CRITICAL RULES:
    - AI GENERATES complete LaTeX documents from scratch (no templates)
    - AI CUSTOMIZES content, it does NOT invent
    - All output must be validated before use
    - Hallucinations cause hard failures
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'AI_AGENT_URL', 'http://localhost:8001')
        # Set timeout to at least 180 seconds to account for Gemini API latency (120s) + processing time
        self.timeout = getattr(settings, 'AI_AGENT_TIMEOUT', 180)
    
    async def generate_resume(
        self,
        profile_data: dict,
        job_description_text: str,
        template_content: str,
        template_id: str
    ) -> AIGenerationResult:
        """
        Request the AI agent to generate a complete resume LaTeX document.
        
        Args:
            profile_data: User's profile data (validated JSON)
            job_description_text: Raw job description text
            template_content: LaTeX template content (deprecated - no longer used, kept for backward compatibility)
            template_id: ID for logging/identification purposes
        
        Returns:
            AIGenerationResult with LaTeX source and modifications
        
        Raises:
            AIServiceException: If the AI service fails
            ModelOutputInvalidException: If the output is invalid
            
        NOTE: The AI now generates complete LaTeX documents from scratch.
        The template_content parameter is ignored but kept for API compatibility.
        """
        logger.info("[AI Agent Client] Called for template: %s", template_id)
        logger.debug("[AI Agent Client] Input profile keys: %s", list(profile_data.keys()))
        logger.debug("[AI Agent Client] Job description length: %d chars", len(job_description_text))
        logger.debug("[AI Agent Client] Template content length: %d chars", len(template_content))
        
        # SECURITY: Whitelist profile data before sending to AI
        # This ensures sensitive fields (contact_info, profile_picture.url, address) are never sent
        logger.info("[AI Agent Client] Whitelisting profile data (removing sensitive fields)")
        safe_profile_data = whitelist_profile_for_ai(profile_data)
        logger.debug("[AI Agent Client] Whitelisted profile keys: %s", list(safe_profile_data.keys()))
        
        # Log profile structure summary
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
            # Call the actual AI agent microservice
            logger.info("[AI Agent Client] Sending request to AI agent service at: %s/generate", self.base_url)
            logger.debug("[AI Agent Client] Request payload size: profile=%d bytes, job_description=%d bytes, template=%d bytes",
                        len(str(safe_profile_data)), len(job_description_text), len(template_content))
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/generate",
                    json={
                        "profile": safe_profile_data,
                        "job_description": job_description_text,
                        "template": template_content,
                        "template_id": template_id,
                    }
                )
                logger.info("[AI Agent Client] Received response from AI agent service (status: %d)", response.status_code)
                
                # Handle error responses from agent
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_detail = error_data.get('detail', 'AI generation failed')
                        
                        if isinstance(error_detail, dict):
                            error_msg = error_detail.get('error', str(error_detail))
                            error_code = error_detail.get('code', 'AI_SERVICE_ERROR')
                        else:
                            error_msg = str(error_detail)
                            error_code = 'AI_SERVICE_ERROR'
                        
                        # Check if it's a quota error (503 status usually indicates quota/service unavailable)
                        if response.status_code == 503 or 'quota' in error_msg.lower():
                            logger.error("AI service quota exceeded: %s", error_msg)
                            raise AIServiceQuotaExceededException(error_msg)
                        elif error_code == 'MODEL_OUTPUT_INVALID':
                            logger.error("AI output validation failed: %s", error_msg)
                            raise ModelOutputInvalidException(error_msg)
                        else:
                            logger.error("AI service error: %s", error_msg)
                            raise AIServiceException(error_msg)
                    except (AIServiceException, AIServiceQuotaExceededException, ModelOutputInvalidException):
                        # Re-raise our own exceptions
                        raise
                    except Exception:
                        error_msg = f"AI service returned status {response.status_code}"
                        logger.error("AI agent error: %s", error_msg)
                        raise AIServiceException(error_msg)
                
                result = response.json()
                logger.debug("[AI Agent Client] Response parsed successfully")
            
            # Validate the response structure
            logger.info("[AI Agent Client] Validating AI agent response structure")
            self._validate_response_structure(result)
            logger.info("[AI Agent Client] Response structure validation passed")
            
            # Validate LaTeX starts with \documentclass
            latex_source = result['latex_source']
            logger.info("[AI Agent Client] Received LaTeX source (length: %d chars)", len(latex_source))
            
            if not latex_source.strip().startswith('\\documentclass'):
                logger.error("[AI Agent Client] AI output does not start with \\documentclass")
                logger.debug("[AI Agent Client] First 100 chars of output: %s", latex_source[:100])
                raise ModelOutputInvalidException(
                    "AI output is not valid LaTeX (must start with \\documentclass)."
                )
            
            logger.info("[AI Agent Client] LaTeX source validation passed. Modifications: %s", result.get('modifications', []))
            
            return AIGenerationResult(
                latex_source=latex_source,
                modifications=result.get('modifications', []),
                raw_response=result
            )
            
        except httpx.TimeoutException:
            logger.error("AI agent request timed out")
            raise AIServiceException("AI service timed out. Please try again.")
        except httpx.HTTPError as e:
            logger.error("AI agent HTTP error: %s", str(e))
            raise AIServiceException("AI service is unavailable.")
        except ModelOutputInvalidException:
            # Re-raise our own exceptions
            raise
        except KeyError as e:
            logger.error("AI agent response missing field: %s", str(e))
            raise ModelOutputInvalidException(f"AI response missing required field: {e}")
    
    def _validate_response_structure(self, response: dict) -> None:
        """
        Validate the basic structure of the AI response.
        
        Args:
            response: The parsed JSON response
        
        Raises:
            ModelOutputInvalidException: If structure is invalid
        """
        if 'latex_source' not in response:
            raise ModelOutputInvalidException("AI response missing 'latex_source' field")
        
        if not isinstance(response['latex_source'], str):
            raise ModelOutputInvalidException("'latex_source' must be a string")
        
        if not response['latex_source'].strip():
            raise ModelOutputInvalidException("'latex_source' cannot be empty")
        
        if 'modifications' in response:
            if not isinstance(response['modifications'], list):
                raise ModelOutputInvalidException("'modifications' must be a list")
    
    def _generate_stub_response(
        self,
        profile_data: dict,
        job_description_text: str
    ) -> dict:
        """
        Generate a stub response for development/testing.
        
        WARNING: This is NOT production code.
        Replace with actual AI service integration.
        
        SECURITY: All profile data is LaTeX-escaped to prevent injection.
        """
        # Sanitize all profile data for LaTeX
        safe_profile = sanitize_profile_for_latex(profile_data)
        
        personal_info = safe_profile.get('personalInfo', {})
        name = personal_info.get('full_name', 'Unknown')
        email = personal_info.get('email', '')
        phone = personal_info.get('phone_number', '')
        location = personal_info.get('location', '')
        summary = safe_profile.get('summary', '')
        
        # Build experience section
        experience_latex = ""
        for exp in safe_profile.get('experience', []):
            company = exp.get('company', '')
            title = exp.get('title', '')
            start_date = exp.get('start_date', '')
            end_date = exp.get('end_date', 'Present') or 'Present'
            description = exp.get('description', '')
            
            experience_latex += f"""
\\subsection*{{{title} at {company}}}
\\textit{{{start_date} -- {end_date}}}

{description}
"""
        
        # Build education section
        education_latex = ""
        for edu in safe_profile.get('education', []):
            institution = edu.get('institution', '')
            degree = edu.get('degree', '')
            start_date = edu.get('start_date', '')
            end_date = edu.get('end_date', '') or 'Present'
            
            education_latex += f"""
\\subsection*{{{degree}}}
\\textit{{{institution}}} \\hfill {start_date} -- {end_date}
"""
        
        # Build skills (already escaped)
        skills = safe_profile.get('skills', [])
        skills_latex = ', '.join(skills) if skills else 'Not specified'
        
        # Generate the full LaTeX document
        latex_source = f"""\\documentclass[11pt,a4paper]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{hyperref}}

\\begin{{document}}

% Header
\\begin{{center}}
\\textbf{{\\LARGE {name}}}

{email} | {phone} | {location}
\\end{{center}}

% Summary
\\section*{{Professional Summary}}
{summary}

% Experience
\\section*{{Experience}}
{experience_latex}

% Education
\\section*{{Education}}
{education_latex}

% Skills
\\section*{{Skills}}
{skills_latex}

\\end{{document}}
"""
        
        return {
            'latex_source': latex_source,
            'modifications': [
                'Generated resume from profile data',
                'Formatted for ATS compatibility',
            ]
        }


# Singleton instance for convenience
ai_agent_client = AIAgentClient()
