"""AI Agent Microservice for Resume AI Platform.

This service handles resume generation using NVIDIA NIM (OpenAI-compatible API).
It customizes a fixed ATS LaTeX template using the candidate profile, job description,
and an explicit list of selected profile sections.

CRITICAL RULES:
- The AI CUSTOMIZES the provided LaTeX template (does not generate from scratch)
- Only SELECTED_SECTIONS (+ personalInfo header) appear in the output
- The AI CUSTOMIZES content, it does NOT invent
- All company names, institutions, dates must come from the profile
- The output must be valid LaTeX that compiles
- The output must be ATS-friendly (single-column, simple layout)

SECURITY:
- User inputs are sanitized to prevent prompt injection
- LaTeX special characters are escaped
"""

import os
import re
import logging
import json
import asyncio
import time
from dataclasses import dataclass
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from openai import OpenAI, APIStatusError, APITimeoutError, RateLimitError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Resume AI Agent",
    description="AI-powered resume customization service using NVIDIA NIM",
    version="1.0.0"
)

# Configure NVIDIA NIM (OpenAI-compatible cloud API)
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_API_BASE_URL = os.getenv("NVIDIA_API_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")
NVIDIA_REQUEST_TIMEOUT = int(os.getenv("NVIDIA_REQUEST_TIMEOUT", "180"))

nim_client: Optional[OpenAI] = None
if NVIDIA_API_KEY:
    nim_client = OpenAI(base_url=NVIDIA_API_BASE_URL, api_key=NVIDIA_API_KEY)
else:
    logger.warning("NVIDIA_API_KEY not set. AI generation will fail.")

_SECTION_HEADING_RE = re.compile(r'\\(?:section\*?\{|resumeSectionTitle\{)')


def _has_section_headings(text: str) -> bool:
    return bool(_SECTION_HEADING_RE.search(text))


def _has_section_body_content(text: str) -> bool:
    """True when the document body has substantive section content."""
    if re.search(
        r'\\(?:item|resumeItem|resumeDetailLine|resumeSkillLine|resumeSummaryText|'
        r'resumeEducationEntry|resumeProjectEntry|resumeExperienceHeading)\{',
        text,
    ):
        return True
    stripped = re.sub(r'\\resumeSectionTitle\{[^}]+\}', '', text)
    stripped = re.sub(r'\\resumeHeader\{[^}]+\}', '', stripped)
    stripped = re.sub(r'\\resumeContactLine\{[^}]+\}', '', stripped)
    stripped = re.sub(r'\\begin\{document\}|\\end\{document\}', '', stripped)
    stripped = re.sub(r'\s+', '', stripped)
    return len(stripped) > 80


# =============================================================================
# SECURITY: Input Sanitization
# =============================================================================

# Patterns that might indicate prompt injection attempts
INJECTION_PATTERNS = [
    r'ignore\s+(all\s+)?(previous|above|prior)\s+instructions?',
    r'disregard\s+(all\s+)?(previous|above|prior)',
    r'forget\s+(all\s+)?(previous|above|prior)',
    r'you\s+are\s+now\s+a',
    r'new\s+instructions?:',
    r'system\s*:\s*',
    r'<\s*system\s*>',
    r'\[\s*system\s*\]',
]

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
    '\\': r'\textbackslash{}',
}


def sanitize_for_prompt(text: str) -> str:
    """
    Sanitize user input to prevent prompt injection.
    
    This function:
    1. Removes potential injection patterns
    2. Escapes special delimiters
    3. Truncates excessively long inputs
    """
    if not text:
        return text
    
    # Truncate to reasonable length (20KB max for JD)
    text = text[:20000]
    
    # Check for and log potential injection attempts (but don't block - just sanitize)
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            logger.warning("Potential prompt injection pattern detected and sanitized")
            # Replace the pattern with safe placeholder
            text = re.sub(pattern, '[FILTERED]', text, flags=re.IGNORECASE)
    
    # Escape XML/HTML-like tags that could confuse the model
    text = re.sub(r'<\s*/?(?:system|user|assistant|instruction|prompt)[^>]*>', '[TAG]', text, flags=re.IGNORECASE)
    
    return text


def escape_latex(text: str) -> str:
    """
    Escape LaTeX special characters in user-provided text.
    
    This prevents LaTeX injection attacks where malicious input
    could execute arbitrary TeX commands.
    """
    if not text:
        return text
    
    # First escape backslashes, then other special chars
    result = text.replace('\\', r'\textbackslash{}')
    
    for char, replacement in LATEX_SPECIAL_CHARS.items():
        if char != '\\':  # Already handled
            result = result.replace(char, replacement)
    
    return result


def sanitize_profile_for_latex(profile: dict) -> dict:
    """
    Recursively escape LaTeX special characters in all string values of the profile.
    """
    if isinstance(profile, dict):
        return {k: sanitize_profile_for_latex(v) for k, v in profile.items()}
    elif isinstance(profile, list):
        return [sanitize_profile_for_latex(item) for item in profile]
    elif isinstance(profile, str):
        return escape_latex(profile)
    else:
        return profile


ALLOWED_PROFILE_SECTIONS = frozenset({
    'personalInfo',
    'summary',
    'experience',
    'education',
    'skills',
    'certifications',
    'projects',
    'achievements',
    'publications',
    'patents',
    'licenses',
    'trainings',
    'volunteering',
    'organizations',
    'positions',
    'career_breaks',
    'languages',
    'test_scores',
    'areas_of_interest',
    'hobbies',
})


class GenerationRequest(BaseModel):
    """Request model for template-based resume generation."""
    profile: dict
    job_description: str
    template: str
    template_id: str
    selected_sections: list[str]

    @field_validator('job_description')
    @classmethod
    def validate_job_description(cls, v: str) -> str:
        """Validate and sanitize job description."""
        if not v or not v.strip():
            raise ValueError('Job description cannot be empty')
        if len(v) > 20000:
            raise ValueError('Job description exceeds maximum length')
        return sanitize_for_prompt(v.strip())

    @field_validator('template')
    @classmethod
    def validate_template(cls, v: str) -> str:
        """Require non-empty ATS reference template content."""
        if not v or not v.strip():
            raise ValueError('Template content cannot be empty')
        if len(v) > 500000:
            raise ValueError('Template content exceeds maximum length')
        return v

    @field_validator('template_id')
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        """Validate template ID format."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Invalid template ID format')
        return v

    @field_validator('selected_sections')
    @classmethod
    def validate_selected_sections(cls, v: list[str]) -> list[str]:
        """Validate selected profile section keys."""
        if not v:
            raise ValueError('At least one section must be selected')
        invalid = set(v) - ALLOWED_PROFILE_SECTIONS
        if invalid:
            raise ValueError(f'Invalid section keys: {sorted(invalid)}')
        return list(dict.fromkeys(v))


class GenerationResponse(BaseModel):
    """Response model for resume generation."""
    latex_source: str
    modifications: list[str]


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


def load_system_prompt() -> str:
    """Load the system prompt from file."""
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'resume_customization.txt')
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Prompt file not found, using fallback")
        return ""


SYSTEM_PROMPT = load_system_prompt()


def build_user_prompt(
    selected_sections: list[str],
    job_description: str,
    profile_json: str,
    template_content: str,
) -> str:
    """Build structured user message with template, sections, JD, and profile."""
    sections_json = json.dumps(selected_sections)
    return f"""SELECTED_SECTIONS: {sections_json}

=== BEGIN JOB DESCRIPTION ===
{job_description}
=== END JOB DESCRIPTION ===

=== BEGIN CANDIDATE PROFILE (JSON) ===
{profile_json}
=== END CANDIDATE PROFILE ===

=== BEGIN LATEX TEMPLATE ===
{template_content}
=== END LATEX TEMPLATE ===

Customize the template per your instructions. Rewrite all narrative content (summary, bullets, skill groupings) for the target role — do not embed raw profile JSON text. Include ONLY sections in SELECTED_SECTIONS (plus personalInfo header). Output ONLY the complete LaTeX document — no markdown fences or commentary."""


@dataclass
class NimChatResult:
    """Result from an NVIDIA NIM chat completion call."""
    content: str
    finish_reason: Optional[str] = None


async def call_nim_chat(messages: list, max_tokens: int = 16384) -> NimChatResult:
    """
    Call NVIDIA NIM chat completions with retry logic.

    Uses OpenAI-compatible API with thinking disabled for structured LaTeX output.
    """
    if not nim_client:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY is not configured")

    max_retries = 2
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(
                "[AI Agent Service] Calling NVIDIA NIM API (model: %s, attempt %d/%d)",
                NVIDIA_MODEL,
                attempt + 1,
                max_retries + 1,
            )
            response = nim_client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=messages,
                temperature=0.7,
                top_p=0.95,
                max_tokens=max_tokens,
                timeout=NVIDIA_REQUEST_TIMEOUT,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            choice = response.choices[0]
            content = (choice.message.content or "").strip()
            finish_reason = choice.finish_reason
            logger.info("[AI Agent Service] NIM response finish reason: %s", finish_reason)
            return NimChatResult(content=content, finish_reason=finish_reason)
        except RateLimitError as model_error:
            logger.error("NVIDIA NIM API quota/rate limit exceeded: %s", model_error)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "AI service quota exceeded. Please try again later.",
                    "code": "AI_SERVICE_ERROR",
                },
            ) from model_error
        except APIStatusError as model_error:
            error_msg = str(model_error).lower()
            last_error = model_error
            if model_error.status_code == 404 or "not found" in error_msg:
                logger.error("NVIDIA NIM model not found: %s, error: %s", NVIDIA_MODEL, model_error)
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": f"AI model '{NVIDIA_MODEL}' not available. Please check configuration.",
                        "code": "AI_SERVICE_ERROR",
                    },
                ) from model_error
            if attempt < max_retries:
                logger.warning(
                    "NVIDIA NIM API attempt %d failed, retrying: %s",
                    attempt + 1,
                    model_error,
                )
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error("NVIDIA NIM API failed after %d attempts: %s", max_retries + 1, model_error)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "AI service is temporarily unavailable. Please try again.",
                    "code": "AI_SERVICE_ERROR",
                },
            ) from model_error
        except APITimeoutError as model_error:
            last_error = model_error
            if attempt < max_retries:
                logger.warning(
                    "NVIDIA NIM API timeout on attempt %d, retrying: %s",
                    attempt + 1,
                    model_error,
                )
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error("NVIDIA NIM API timed out after %d attempts", max_retries + 1)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "AI service is temporarily unavailable. Please try again.",
                    "code": "AI_SERVICE_ERROR",
                },
            ) from model_error
        except Exception as model_error:
            error_msg = str(model_error).lower()
            last_error = model_error
            if "quota" in error_msg or "rate limit" in error_msg:
                logger.error("NVIDIA NIM API quota exceeded: %s", model_error)
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "AI service quota exceeded. Please try again later.",
                        "code": "AI_SERVICE_ERROR",
                    },
                ) from model_error
            if attempt < max_retries:
                logger.warning(
                    "NVIDIA NIM API attempt %d failed, retrying: %s",
                    attempt + 1,
                    model_error,
                )
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error("NVIDIA NIM API failed after %d attempts: %s", max_retries + 1, model_error)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "AI service is temporarily unavailable. Please try again.",
                    "code": "AI_SERVICE_ERROR",
                },
            ) from model_error

    raise HTTPException(
        status_code=503,
        detail={
            "error": "AI service is temporarily unavailable. Please try again.",
            "code": "AI_SERVICE_ERROR",
        },
    ) from last_error


def fix_mismatched_environments(source: str) -> str:
    """
    Fix mismatched begin/end environment names using a stack-based approach.
    
    This function ensures that every \\begin{env} is closed with \\end{env} (matching name).
    It handles:
    - Direct mismatches: \begin{itemize}...\end{enumerate}
    - Variant names: \begin{itemize}...\end{tightitemize}
    - All LaTeX environments, not just itemize/enumerate
    
    CRITICAL: Uses stack-based approach to avoid matching across section boundaries.
    """
    # Find all \begin{env} and \end{env} positions
    begin_pattern = r'\\begin\{([^}]+)\}'
    end_pattern = r'\\end\{([^}]+)\}'
    
    begins = []
    ends = []
    
    for match in re.finditer(begin_pattern, source):
        env_name = match.group(1)
        begins.append((env_name, match.start(), match.end()))
    
    for match in re.finditer(end_pattern, source):
        env_name = match.group(1)
        ends.append((env_name, match.start(), match.end()))
    
    # Normalize environment names for matching
    def normalize_env_name(name: str) -> str:
        name_lower = name.lower()
        if 'itemize' in name_lower:
            return 'itemize'
        elif 'enumerate' in name_lower:
            return 'enumerate'
        elif 'description' in name_lower:
            return 'description'
        return name
    
    # Build a list of all environment positions sorted by position
    all_envs = []
    for name, start, end in begins:
        all_envs.append(('begin', name, start, end))
    for name, start, end in ends:
        all_envs.append(('end', name, start, end))
    
    all_envs.sort(key=lambda x: x[2])  # Sort by position
    
    # Use a stack to track open environments and fix mismatches
    stack = []
    fixes = []  # List of (start_pos, end_pos, replacement) tuples
    
    for env_type, env_name, start_pos, end_pos in all_envs:
        normalized_name = normalize_env_name(env_name)
        
        if env_type == 'begin':
            stack.append((normalized_name, env_name, start_pos, end_pos))
        else:  # end
            if stack:
                expected_normalized, expected_original, expected_start, expected_end = stack[-1]
                
                # Check if this end matches the most recent begin
                if normalized_name == expected_normalized:
                    # Match! Pop from stack
                    stack.pop()
                else:
                    # Mismatch! Fix the end to match the begin
                    # Replace \end{actual_name} with \end{expected_name}
                    fixes.append((start_pos, end_pos, f'\\end{{{expected_original}}}'))
                    stack.pop()
            else:
                # Extra closing tag - will be handled by close_unclosed_environments
                pass
    
    # Apply fixes in reverse order (from end to start) to preserve positions
    fixes.sort(key=lambda x: x[0], reverse=True)
    for start_pos, end_pos, replacement in fixes:
        source = source[:start_pos] + replacement + source[end_pos:]
    
    return source


def close_unclosed_environments(source: str) -> str:
    """Close any unclosed \\begin{...} environments before \\end{document}."""
    if '\\end{document}' not in source:
        return source
    
    # Find all \begin{env} and \end{env}
    begin_pattern = r'\\begin\{([^}]+)\}'
    end_pattern = r'\\end\{([^}]+)\}'
    
    begins = []
    ends = []
    
    for match in re.finditer(begin_pattern, source):
        env_name = match.group(1)
        begins.append((env_name, match.start()))
    
    for match in re.finditer(end_pattern, source):
        env_name = match.group(1)
        ends.append((env_name, match.start()))
    
    # Build a stack to track open environments
    env_stack = []
    begin_map = {pos: name for name, pos in begins}
    end_map = {pos: name for name, pos in ends}
    
    all_positions = sorted(set(begin_map.keys()) | set(end_map.keys()))
    
    for pos in all_positions:
        if pos in begin_map:
            env_name = begin_map[pos]
            env_stack.append(env_name)
        elif pos in end_map:
            env_name = end_map[pos]
            if env_stack and env_stack[-1] == env_name:
                env_stack.pop()
            elif env_stack:
                # Mismatch - but we'll handle that separately
                # For now, try to match by popping from stack
                # This handles nested cases
                found_match = False
                for i in range(len(env_stack) - 1, -1, -1):
                    if env_stack[i] == env_name:
                        env_stack = env_stack[:i] + env_stack[i+1:]
                        found_match = True
                        break
                if not found_match:
                    # Extra closing - ignore for now
                    pass
    
    # Close any remaining open environments before \end{document}
    if env_stack:
        # Find position of \end{document}
        end_doc_pos = source.find('\\end{document}')
        if end_doc_pos != -1:
            # Build closing tags in reverse order (LIFO)
            closing_tags = []
            for env_name in reversed(env_stack):
                closing_tags.append(f'\\end{{{env_name}}}')
            
            # Insert closing tags before \end{document}
            closing_text = '\n' + '\n'.join(closing_tags) + '\n'
            source = source[:end_doc_pos] + closing_text + source[end_doc_pos:]
    
    return source


def fix_latex_issues(latex_source: str) -> str:
    """
    Fix common LaTeX issues that cause compilation failures.
    
    This function attempts to fix known problematic patterns while
    preserving the overall document structure.
    
    CRITICAL: This function must NOT remove sections or significant content.
    """
    # Store original to check for content loss
    original_latex = latex_source
    original_has_sections = _has_section_headings(original_latex)
    
    # Remove titlesec package if present (causes \hrule issues)
    latex_source = re.sub(r'\\usepackage(\[.*?\])?\{titlesec\}', '', latex_source)
    
    # Remove any \titleformat or \titlespacing commands
    latex_source = re.sub(r'\\titleformat\{[^}]*\}.*?(?=\\|\n\n|\Z)', '', latex_source, flags=re.DOTALL)
    latex_source = re.sub(r'\\titlespacing\*?\{[^}]*\}.*', '', latex_source)
    
    # CRITICAL: Fix mismatched environments FIRST
    # This must run before other fixes to ensure proper structure
    # Use stack-based approach which is safe even with sections
    latex_source_before_env_fix = latex_source
    latex_source = fix_mismatched_environments(latex_source)
    
    # Verify sections are still present after environment fixes
    if original_has_sections:
        after_fix_has_sections = _has_section_headings(latex_source)
        if not after_fix_has_sections:
            logger.error("[fix_latex_issues] CRITICAL: Sections were removed by fix_mismatched_environments! Restoring original.")
            latex_source = latex_source_before_env_fix
    
    # Replace problematic \hrule and \rule inside document body
    # Keep them in preamble but convert problematic ones in body
    parts = latex_source.split('\\begin{document}')
    logger.debug("[fix_latex_issues] Split on \\begin{document}: %d parts", len(parts))
    if len(parts) == 2:
        preamble, body = parts
        logger.debug("[fix_latex_issues] Body length before fixes: %d chars", len(body))
        # In body, replace \hrule with a simple line using \par
        body = re.sub(r'\\hrule', r'\\par\\vspace{2pt}\\noindent\\rule{\\textwidth}{0.4pt}\\par\\vspace{2pt}', body)
        
        # CRITICAL: Store original body to detect content loss
        original_body_for_fixes = body
        original_body_length_for_fixes = len(body)
        original_body_has_sections = _has_section_headings(body)
        
        # Fix itemize/enumerate issues - "missing \item" errors
        # ONLY remove TRULY empty environments (no content at all, just whitespace)
        # Use a very restrictive pattern that only matches immediately adjacent begin/end
        body = re.sub(r'\\begin\{(itemize|enumerate)\}\s*\\end\{(itemize|enumerate)\}', '', body)
        
        # Fix itemize/enumerate with text before first \item
        # Pattern: \begin{itemize}\n[text]\n\item -> \begin{itemize}\n\item
        # BUT: Only if text is short and doesn't contain sections
        def fix_text_before_item(match):
            env_type = match.group(1)
            prefix = match.group(2)
            text_before = match.group(3)
            # Only fix if text is short and doesn't contain sections
            if len(text_before) < 100 and '\\section' not in text_before:
                return f'\\begin{{{env_type}}}{prefix}\n\\item'
            return match.group(0)  # Keep original if suspicious
        
        body = re.sub(
            r'\\begin\{(itemize|enumerate)\}([^\n]*)\n+([^\\\n]+?)\n+\\item',
            fix_text_before_item,
            body,
            flags=re.MULTILINE
        )
        
        # Fix itemize/enumerate with blank lines before first \item
        body = re.sub(
            r'\\begin\{(itemize|enumerate)\}([^\n]*)\n+\n+\\item',
            r'\\begin{\1}\2\n\\item',
            body
        )
        
        # CRITICAL: DO NOT remove list environments that might contain sections
        # The previous aggressive removal was causing content loss
        # Instead, we'll let LaTeX compiler catch empty list errors and fix them there
        
        # Verify we didn't lose content
        body_length_after_fixes = len(body)
        body_has_sections_after = bool(re.search(r'\\section\*?\{', body))
        
        if body_length_after_fixes < original_body_length_for_fixes * 0.9:
            logger.error("[fix_latex_issues] CRITICAL: Body length reduced significantly (%d -> %d chars). Reverting empty list fixes.", 
                         original_body_length_for_fixes, body_length_after_fixes)
            body = original_body_for_fixes
        elif original_body_has_sections and not body_has_sections_after:
            logger.error("[fix_latex_issues] CRITICAL: Sections were removed! Reverting empty list fixes.")
            body = original_body_for_fixes
        
        # Fix unmatched itemize/enumerate environments
        # Count opens and closes, remove extras
        itemize_opens = len(re.findall(r'\\begin\{itemize\}', body))
        itemize_closes = len(re.findall(r'\\end\{itemize\}', body))
        enumerate_opens = len(re.findall(r'\\begin\{enumerate\}', body))
        enumerate_closes = len(re.findall(r'\\end\{enumerate\}', body))
        
        # If there are more closes than opens, remove extra closes from the end
        if itemize_closes > itemize_opens:
            for _ in range(itemize_closes - itemize_opens):
                body = re.sub(r'\\end\{itemize\}', '', body, count=1)
        
        if enumerate_closes > enumerate_opens:
            for _ in range(enumerate_closes - enumerate_opens):
                body = re.sub(r'\\end\{enumerate\}', '', body, count=1)
        
        # If there are more opens than closes, add missing closes at the end (before \end{document})
        if itemize_opens > itemize_closes:
            missing = itemize_opens - itemize_closes
            # Add before \end{document} - use string replacement instead of regex to avoid escape issues
            # Build the replacement string with proper escaping for literal backslashes
            replacement_parts = [r'\end{itemize}'] * missing + [r'\end{document}']
            replacement = '\n'.join(replacement_parts)
            # Use string replace instead of regex to avoid backslash interpretation issues
            body = body.replace(r'\end{document}', replacement, 1)
        
        if enumerate_opens > enumerate_closes:
            missing = enumerate_opens - enumerate_closes
            # Use string replacement instead of regex to avoid escape issues
            replacement_parts = [r'\end{enumerate}'] * missing + [r'\end{document}']
            replacement = '\n'.join(replacement_parts)
            body = body.replace(r'\end{document}', replacement, 1)
        
        logger.debug("[fix_latex_issues] Body length after fixes: %d chars", len(body))
        
        # CRITICAL CHECK: Verify sections are still in body
        body_has_sections = _has_section_headings(body)
        if original_has_sections and not body_has_sections:
            logger.error("[fix_latex_issues] CRITICAL: Sections were removed from body! Restoring original body.")
            # Restore original body
            original_parts = original_latex.split('\\begin{document}')
            if len(original_parts) == 2:
                body = original_parts[1]
        
        latex_source = preamble + '\\begin{document}' + body
        logger.debug("[fix_latex_issues] Reconstructed LaTeX length: %d chars", len(latex_source))
    
    # Remove any \titlerule commands (from titlesec)
    latex_source = re.sub(r'\\titlerule(\[.*?\])?', '', latex_source)
    
    # Fix duplicate command definitions
    # Convert duplicate \newcommand to \providecommand (safer than removing)
    parts = latex_source.split('\\begin{document}')
    logger.debug("[fix_latex_issues] Second split on \\begin{document}: %d parts", len(parts))
    if len(parts) == 2:
        preamble, body = parts
        logger.debug("[fix_latex_issues] Body length before command fix: %d chars", len(body))
        commands_defined = set()
        lines = preamble.split('\n')
        result_lines = []
        
        for line in lines:
            # Check for \newcommand or \renewcommand
            match = re.search(r'(\s*)\\(?:new|renew)command(\*?)(\[[^\]]*\])?\{([^}]+)\}(\[[^\]]*\])?', line)
            if match:
                cmd_name = match.group(4)  # Extract command name
                if cmd_name in commands_defined:
                    # Convert to \providecommand for duplicates
                    line = re.sub(
                        r'\\(?:new|renew)command(\*?)(\[[^\]]*\])?\{([^}]+)\}(\[[^\]]*\])?',
                        r'\\providecommand\1\2{\3}\4',
                        line,
                        count=1
                    )
                else:
                    commands_defined.add(cmd_name)
            result_lines.append(line)
        
        preamble = '\n'.join(result_lines)
        logger.debug("[fix_latex_issues] Body length after command fix: %d chars", len(body))
        latex_source = preamble + '\\begin{document}' + body
        logger.debug("[fix_latex_issues] Final LaTeX length: %d chars", len(latex_source))
    
    # CRITICAL: Close any unclosed environments before \end{document}
    # This prevents errors like "\begin{center} ended by \end{document}"
    latex_source = close_unclosed_environments(latex_source)
    
    # Fix mismatched environments again after closing unclosed ones
    # This catches any new mismatches introduced by closing
    latex_source = fix_mismatched_environments(latex_source)
    
    # Fix math mode issues - ensure $|$ separators are properly closed
    # Count $ signs and ensure they're balanced
    dollar_count = latex_source.count('$')
    if dollar_count % 2 != 0:
        # Add closing $ if odd number (but be careful not to break valid math)
        # Only fix if it's clearly a separator issue
        if '$|$' in latex_source:
            # Check if there's an unclosed $ before \end{center}
            if '\\end{center}' in latex_source:
                # Ensure math mode is closed before \end{center}
                latex_source = re.sub(r'(\$[^$]*)\n\s*\\end\{center\}', r'\1$\n\\end{center}', latex_source)
    
    # Fix common escaping issues
    # Double backslashes that aren't line breaks
    latex_source = re.sub(r'\\\\(?![\\n\s])', r'\\', latex_source)
    
    # Remove empty lines that might cause issues
    latex_source = re.sub(r'\n{4,}', '\n\n\n', latex_source)
    
    return latex_source


@app.post("/generate", response_model=GenerationResponse)
async def generate_resume(request: GenerationRequest):
    """
    Customize the ATS LaTeX template for the candidate profile and job description.

    The AI receives the full reference template, filtered profile JSON, job description,
    and SELECTED_SECTIONS. It returns a complete compile-ready document containing only
    the selected sections (+ personalInfo header).

    Security measures:
    - Job description is sanitized against prompt injection
    - Profile data has LaTeX special characters escaped
    - Strict output validation

    CRITICAL: This endpoint must NEVER return hallucinated content.
    """
    if not NVIDIA_API_KEY:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY is not configured")

    logger.info(
        "[AI Agent Service] Customizing template %s for sections: %s",
        request.template_id,
        request.selected_sections,
    )
    
    try:
        logger.info("[AI Agent Service] Sanitizing user profile for LaTeX (escaping special characters)")
        safe_profile = sanitize_profile_for_latex(request.profile)
        profile_json = json.dumps(safe_profile, indent=2)
        logger.info("[AI Agent Service] Profile sanitized. Profile JSON length: %d chars", len(profile_json))
        
        profile_summary = {
            'selected_sections': request.selected_sections,
            'profile_keys': list(safe_profile.keys()),
        }
        logger.info("[AI Agent Service] Parsed user profile summary: %s", profile_summary)
        
        safe_jd = request.job_description
        logger.info("[AI Agent Service] Job description length: %d chars", len(safe_jd))
        logger.info("[AI Agent Service] Template content length: %d chars", len(request.template))
        
        user_prompt = build_user_prompt(
            selected_sections=request.selected_sections,
            job_description=safe_jd,
            profile_json=profile_json,
            template_content=request.template,
        )
        
        logger.info(
            "[AI Agent Service] Prompt summary - System: %d chars, User: %d chars",
            len(SYSTEM_PROMPT),
            len(user_prompt),
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("[AI Agent Service] Using NVIDIA NIM model: %s", NVIDIA_MODEL)

        nim_result = await call_nim_chat(messages)
        latex_source = nim_result.content

        if nim_result.finish_reason == "length":
            logger.warning("[AI Agent Service] Response was truncated due to token limit")
        
        logger.info("[AI Agent Service] Received raw response from NVIDIA NIM (length: %d chars)", len(latex_source))
        
        # Log a sample of the raw response
        logger.info("[AI Agent Service] Raw response preview (first 1000 chars): %s", latex_source[:1000])
        logger.info("[AI Agent Service] Raw response preview (last 500 chars): %s", latex_source[-500:] if len(latex_source) > 500 else latex_source)
        
        # Check body content in RAW response BEFORE any cleanup
        raw_body_start = latex_source.find('\\begin{document}')
        raw_body_end = latex_source.find('\\end{document}')
        if raw_body_start != -1 and raw_body_end != -1:
            raw_body = latex_source[raw_body_start:raw_body_end]
            raw_body_no_ws = re.sub(r'\s+', '', raw_body)
            raw_has_sections = _has_section_headings(raw_body)
            logger.info("[AI Agent Service] RAW response body check - Length: %d chars, Has sections: %s", 
                       len(raw_body_no_ws), raw_has_sections)
            if raw_has_sections:
                # Extract section names to verify
                section_matches = re.findall(r'\\section\*?\{([^}]+)\}', raw_body)
                logger.info("[AI Agent Service] RAW response contains sections: %s", section_matches[:10])
        
        # Clean up if the model wrapped it in markdown code blocks despite instructions
        logger.debug("[AI Agent Service] Cleaning up markdown code blocks if present")
        if latex_source.startswith("```latex"):
            latex_source = latex_source[8:]
            logger.debug("[AI Agent Service] Removed ```latex prefix")
        elif latex_source.startswith("```"):
            latex_source = latex_source[3:]
            logger.debug("[AI Agent Service] Removed ``` prefix")
        if latex_source.endswith("```"):
            latex_source = latex_source[:-3]
            logger.debug("[AI Agent Service] Removed ``` suffix")
            
        latex_source = latex_source.strip()
        logger.info("[AI Agent Service] Cleaned LaTeX source length: %d chars", len(latex_source))
        
        # Check body content AFTER markdown cleanup
        cleaned_body_start = latex_source.find('\\begin{document}')
        cleaned_body_end = latex_source.find('\\end{document}')
        if cleaned_body_start != -1 and cleaned_body_end != -1:
            cleaned_body = latex_source[cleaned_body_start:cleaned_body_end]
            cleaned_body_no_ws = re.sub(r'\s+', '', cleaned_body)
            cleaned_has_sections = _has_section_headings(cleaned_body)
            logger.info("[AI Agent Service] AFTER markdown cleanup body check - Length: %d chars, Has sections: %s", 
                       len(cleaned_body_no_ws), cleaned_has_sections)
            if cleaned_has_sections:
                section_matches = re.findall(r'\\section\*?\{([^}]+)\}', cleaned_body)
                logger.info("[AI Agent Service] Sections found after cleanup: %s", section_matches[:10])
        
        # Check if output appears incomplete BEFORE validation
        # If it ends abruptly without \end{document}, try to complete it
        if '\\end{document}' not in latex_source:
            logger.warning("[AI Agent Service] Response missing \\end{document}, attempting to complete")
            # Try to add closing tag if document structure exists
            if '\\begin{document}' in latex_source:
                latex_source += '\n\\end{document}'
                logger.info("[AI Agent Service] Added missing \\end{document}")
        
        # Check if output is suspiciously short (likely incomplete)
        # A complete resume should be at least 500-1000 chars after cleaning
        if len(latex_source) < 500:
            logger.warning("[AI Agent Service] Output is very short (%d chars), may be incomplete", len(latex_source))
        
        # Store original body length for comparison
        body_start_orig = latex_source.find('\\begin{document}')
        body_end_orig = latex_source.find('\\end{document}')
        original_body_length = 0
        if body_start_orig != -1 and body_end_orig != -1:
            original_body_content = latex_source[body_start_orig:body_end_orig]
            original_body_length = len(re.sub(r'\s+', '', original_body_content))
            logger.info("[AI Agent Service] Original body length BEFORE fixes: %d chars", original_body_length)
        
        # Fix common LaTeX issues that cause compilation failures
        logger.info("[AI Agent Service] Fixing common LaTeX issues (environment mismatches, unclosed environments, etc.)")
        latex_source_before_fixes = latex_source
        latex_source = fix_latex_issues(latex_source)
        logger.info("[AI Agent Service] LaTeX fixes applied. Final LaTeX source length: %d chars", len(latex_source))
        
        # Check if fixes removed too much content (more than 50% reduction is suspicious)
        body_start_after = latex_source.find('\\begin{document}')
        body_end_after = latex_source.find('\\end{document}')
        if body_start_after != -1 and body_end_after != -1:
            body_content_after = latex_source[body_start_after:body_end_after]
            body_no_ws_after = re.sub(r'\s+', '', body_content_after)
            body_length_after = len(body_no_ws_after)
            
            logger.info("[AI Agent Service] Body length AFTER fixes: %d chars", body_length_after)
            
            # If fixes removed more than 50% of content, something went wrong
            if original_body_length > 0 and body_length_after < (original_body_length * 0.5):
                logger.error("[AI Agent Service] CRITICAL: fix_latex_issues removed too much content! Original: %d, After: %d", 
                           original_body_length, body_length_after)
                logger.error("[AI Agent Service] Body content BEFORE fixes (first 1000 chars): %s", 
                           latex_source_before_fixes[latex_source_before_fixes.find('\\begin{document}'):latex_source_before_fixes.find('\\begin{document}')+1000] if '\\begin{document}' in latex_source_before_fixes else latex_source_before_fixes[:1000])
                logger.error("[AI Agent Service] Body content AFTER fixes (first 1000 chars): %s", 
                           latex_source[latex_source.find('\\begin{document}'):latex_source.find('\\begin{document}')+1000] if '\\begin{document}' in latex_source else latex_source[:1000])
                logger.error("[AI Agent Service] Restoring original LaTeX and skipping aggressive fixes")
                # Restore original and only apply safe fixes
                latex_source = latex_source_before_fixes
                # Apply safe environment fixes (stack-based, doesn't remove content)
                latex_source = fix_mismatched_environments(latex_source)
                latex_source = close_unclosed_environments(latex_source)
                logger.info("[AI Agent Service] Restored original LaTeX with only safe fixes applied")
                
                # Verify restoration worked
                restored_body_start = latex_source.find('\\begin{document}')
                restored_body_end = latex_source.find('\\end{document}')
                if restored_body_start != -1 and restored_body_end != -1:
                    restored_body = latex_source[restored_body_start:restored_body_end]
                    restored_body_no_ws = re.sub(r'\s+', '', restored_body)
                    restored_has_sections = _has_section_headings(restored_body)
                    logger.info("[AI Agent Service] After restoration - Body length: %d chars, Has sections: %s", 
                               len(restored_body_no_ws), restored_has_sections)
                    if restored_has_sections:
                        section_matches = re.findall(r'\\section\*?\{([^}]+)\}', restored_body)
                        logger.info("[AI Agent Service] Sections found after restoration: %s", section_matches[:10])
        
        # Check if body has content sections AFTER fixes
        body_start = latex_source.find('\\begin{document}')
        body_end = latex_source.find('\\end{document}')
        if body_start != -1 and body_end != -1:
            body_content = latex_source[body_start:body_end]
            body_no_ws = re.sub(r'\s+', '', body_content)
            has_sections = _has_section_headings(body_content)
            
            logger.info("[AI Agent Service] Body content check AFTER fixes - Length: %d chars, Has sections: %s", 
                       len(body_no_ws), has_sections)
            
            # If body is very short and has no sections, try to request continuation
            if len(body_no_ws) < 300 and not has_sections:
                logger.warning("[AI Agent Service] Output appears incomplete AFTER fixes - body too short and no sections detected")
                logger.warning("[AI Agent Service] Body preview: %s", body_content[:500])
                
                # Try to continue generation by requesting the AI to complete the document
                logger.info("[AI Agent Service] Attempting to request continuation from AI")
                continuation_prompt = f"""The LaTeX document you produced is incomplete.

SELECTED_SECTIONS: {json.dumps(request.selected_sections)}

Continue customizing the template. Include all selected sections that have profile data, preserve template macros and preamble, and close with \\end{{document}}.

Current incomplete LaTeX (tail):
{latex_source[-800:]}

Continue from where you left off. Output ONLY LaTeX — no markdown fences."""
                
                try:
                    logger.info("[AI Agent Service] Requesting continuation from NVIDIA NIM API")
                    continuation_messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": latex_source},
                        {"role": "user", "content": continuation_prompt},
                    ]
                    continuation_result = await call_nim_chat(continuation_messages)
                    continuation_text = continuation_result.content
                    logger.info("[AI Agent Service] Continuation response received (length: %d chars)", len(continuation_text))
                    
                    # Clean continuation response
                    if continuation_text.startswith("```latex"):
                        continuation_text = continuation_text[8:]
                    elif continuation_text.startswith("```"):
                        continuation_text = continuation_text[3:]
                    if continuation_text.endswith("```"):
                        continuation_text = continuation_text[:-3]
                    continuation_text = continuation_text.strip()
                    
                    # Append continuation to existing LaTeX
                    # Remove only the LAST \end{document} from original (not all occurrences)
                    if '\\end{document}' in latex_source:
                        # Find the last occurrence
                        last_end_doc = latex_source.rfind('\\end{document}')
                        if last_end_doc != -1:
                            latex_source = latex_source[:last_end_doc].rstrip()
                    
                    # Handle continuation text - it might be:
                    # 1. Just the continuation content (sections)
                    # 2. A complete document starting with \documentclass
                    # 3. Body content starting with \begin{document}
                    
                    # Check if continuation is a complete document
                    if continuation_text.startswith('\\documentclass'):
                        # Extract body from continuation document
                        cont_body_start = continuation_text.find('\\begin{document}')
                        cont_body_end = continuation_text.find('\\end{document}')
                        if cont_body_start != -1 and cont_body_end != -1:
                            # Extract just the body content
                            continuation_body = continuation_text[cont_body_start:cont_body_end]
                            latex_source += continuation_body
                            logger.info("[AI Agent Service] Extracted body from continuation document (%d chars)", len(continuation_body))
                        else:
                            # Can't extract body, append as-is
                            latex_source += '\n' + continuation_text
                    elif continuation_text.startswith('\\begin{document}'):
                        # Continuation starts with body
                        cont_body_end = continuation_text.find('\\end{document}')
                        if cont_body_end != -1:
                            continuation_body = continuation_text[:cont_body_end]
                            latex_source += continuation_body
                        else:
                            latex_source += '\n' + continuation_text
                    else:
                        # Continuation is just content (sections, etc.)
                        latex_source += '\n' + continuation_text
                    
                    # Ensure \end{document} exists at the end
                    if not latex_source.rstrip().endswith('\\end{document}'):
                        latex_source += '\n\\end{document}'
                    
                    logger.info("[AI Agent Service] Combined LaTeX source length after continuation: %d chars", len(latex_source))
                    
                    # Verify body length after continuation
                    body_start_check = latex_source.find('\\begin{document}')
                    body_end_check = latex_source.find('\\end{document}')
                    if body_start_check != -1 and body_end_check != -1:
                        body_check = latex_source[body_start_check:body_end_check]
                        body_check_no_ws = re.sub(r'\s+', '', body_check)
                        logger.info("[AI Agent Service] Body length after continuation: %d chars", len(body_check_no_ws))
                    
                    # Re-apply safe fixes after continuation (but don't use fix_latex_issues which removes content)
                    latex_source = fix_mismatched_environments(latex_source)
                    latex_source = close_unclosed_environments(latex_source)
                except Exception as cont_error:
                    logger.error("[AI Agent Service] Continuation request failed: %s", str(cont_error))
                    # Continue with original incomplete output - validation will catch it
        
        # Validate output structure - CRITICAL CHECKS
        if not latex_source.startswith('\\documentclass'):
            logger.error("AI output does not start with \\documentclass")
            raise HTTPException(
                status_code=500, 
                detail={
                    "error": "AI generated invalid output format",
                    "code": "MODEL_OUTPUT_INVALID"
                }
            )
        
        if '\\begin{document}' not in latex_source:
            logger.error("AI output missing \\begin{document}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "AI generated incomplete LaTeX document (missing \\begin{document})",
                    "code": "MODEL_OUTPUT_INVALID"
                }
            )
        
        if '\\end{document}' not in latex_source:
            logger.error("AI output missing \\end{document}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "AI generated incomplete LaTeX document (missing \\end{document})",
                    "code": "MODEL_OUTPUT_INVALID"
                }
            )
        
        # CRITICAL VALIDATION: document must include content for selected sections
        body_start = latex_source.find('\\begin{document}')
        body_end = latex_source.find('\\end{document}')
        if body_start != -1 and body_end != -1:
            body_content = latex_source[body_start:body_end]
            selected = set(request.selected_sections) | {'personalInfo'}
            content_sections = selected - {'personalInfo'}
            has_sections = _has_section_headings(body_content)
            has_list_items = bool(re.search(r'\\item', body_content))
            has_body_content = _has_section_body_content(body_content)
            has_header = bool(re.search(r'\\resumeHeader\{', body_content))

            if not has_header and 'personalInfo' in selected:
                logger.error("AI output missing personalInfo header macros")
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "AI generated incomplete LaTeX document - missing header",
                        "code": "MODEL_OUTPUT_INVALID",
                    },
                )

            if content_sections and not has_sections:
                logger.error("AI output missing section headings for selected sections")
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "AI generated incomplete LaTeX document - missing selected section content",
                        "code": "MODEL_OUTPUT_INVALID",
                    },
                )

            if content_sections and has_sections and not has_list_items and not has_body_content:
                logger.error("AI output has section headers but no list content")
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "AI generated incomplete LaTeX document - sections contain no content",
                        "code": "MODEL_OUTPUT_INVALID",
                    },
                )

        modifications = [
            "Customized template content based on job description keywords",
            f"Included sections: {', '.join(request.selected_sections)}",
            "Preserved ATS-safe template structure",
        ]
        
        logger.info("Resume customization successful for template: %s", request.template_id)
        
        return GenerationResponse(
            latex_source=latex_source,
            modifications=modifications
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error generating resume: %s", type(e).__name__)
        # Don't expose internal error details to prevent information leakage
        raise HTTPException(
            status_code=500, 
            detail={
                "error": "Resume generation failed due to an internal error",
                "code": "AI_SERVICE_ERROR"
            }
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)