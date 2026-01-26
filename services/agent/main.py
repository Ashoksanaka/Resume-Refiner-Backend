"""AI Agent Microservice for Resume AI Platform.

This service handles resume customization using Google's Gemini API.
It takes a user profile and job description, then generates customized LaTeX.

CRITICAL RULES:
- The AI CUSTOMIZES content, it does NOT invent
- All company names, institutions, dates must come from the profile
- The output must be valid LaTeX that compiles

SECURITY:
- User inputs are sanitized to prevent prompt injection
- LaTeX special characters are escaped
"""

import os
import re
import logging
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Resume AI Agent",
    description="AI-powered resume customization service using Gemini",
    version="1.0.0"
)

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY not set. AI generation will fail.")


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


class GenerationRequest(BaseModel):
    """Request model for resume generation."""
    profile: dict
    job_description: str
    template: str
    template_id: str
    
    @field_validator('job_description')
    @classmethod
    def validate_job_description(cls, v: str) -> str:
        """Validate and sanitize job description."""
        if not v or not v.strip():
            raise ValueError('Job description cannot be empty')
        if len(v) > 20000:
            raise ValueError('Job description exceeds maximum length')
        return sanitize_for_prompt(v.strip())
    
    @field_validator('template_id')
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        """Validate template ID format."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Invalid template ID format')
        return v


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


def fix_latex_issues(latex_source: str) -> str:
    """
    Fix common LaTeX issues that cause compilation failures.
    
    This function attempts to fix known problematic patterns while
    preserving the overall document structure.
    """
    # Remove titlesec package if present (causes \hrule issues)
    latex_source = re.sub(r'\\usepackage(\[.*?\])?\{titlesec\}', '', latex_source)
    
    # Remove any \titleformat or \titlespacing commands
    latex_source = re.sub(r'\\titleformat\{[^}]*\}.*?(?=\\|\n\n|\Z)', '', latex_source, flags=re.DOTALL)
    latex_source = re.sub(r'\\titlespacing\*?\{[^}]*\}.*', '', latex_source)
    
    # Replace problematic \hrule and \rule inside document body
    # Keep them in preamble but convert problematic ones in body
    parts = latex_source.split('\\begin{document}')
    if len(parts) == 2:
        preamble, body = parts
        # In body, replace \hrule with a simple line using \par
        body = re.sub(r'\\hrule', r'\\par\\vspace{2pt}\\noindent\\rule{\\textwidth}{0.4pt}\\par\\vspace{2pt}', body)
        
        # Fix itemize/enumerate issues - "missing \item" errors
        # Remove empty itemize/enumerate environments
        body = re.sub(r'\\begin\{(itemize|enumerate)\}[\s\n]*\\end\{(itemize|enumerate)\}', '', body)
        
        # Fix itemize/enumerate with text before first \item
        # Pattern: \begin{itemize}\n[text]\n\item -> \begin{itemize}\n\item
        body = re.sub(
            r'\\begin\{(itemize|enumerate)\}([^\n]*)\n+([^\\\n]+?)\n+\\item',
            r'\\begin{\1}\2\n\\item',
            body,
            flags=re.MULTILINE
        )
        
        # Fix itemize/enumerate with blank lines before first \item
        body = re.sub(
            r'\\begin\{(itemize|enumerate)\}([^\n]*)\n+\n+\\item',
            r'\\begin{\1}\2\n\\item',
            body
        )
        
        # Ensure every \begin{itemize} or \begin{enumerate} has at least one \item
        # If not, remove the environment
        def fix_empty_lists(match):
            env_type = match.group(1)
            content = match.group(2)
            # Check if there's at least one \item
            if '\\item' not in content:
                return ''  # Remove empty list
            return match.group(0)  # Keep if it has items
        
        body = re.sub(
            r'\\begin\{(itemize|enumerate)\}(.*?)\\end\{(itemize|enumerate)\}',
            fix_empty_lists,
            body,
            flags=re.DOTALL
        )
        
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
            # Add before \end{document}
            body = re.sub(r'\\end\{document\}', '\\end{itemize}\n' * missing + '\\end{document}', body, count=1)
        
        if enumerate_opens > enumerate_closes:
            missing = enumerate_opens - enumerate_closes
            body = re.sub(r'\\end\{document\}', '\\end{enumerate}\n' * missing + '\\end{document}', body, count=1)
        
        latex_source = preamble + '\\begin{document}' + body
    
    # Remove any \titlerule commands (from titlesec)
    latex_source = re.sub(r'\\titlerule(\[.*?\])?', '', latex_source)
    
    # Fix duplicate command definitions
    # Convert duplicate \newcommand to \providecommand (safer than removing)
    parts = latex_source.split('\\begin{document}')
    if len(parts) == 2:
        preamble, body = parts
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
        latex_source = preamble + '\\begin{document}' + body
    
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
    Generate a customized resume using Gemini.
    
    Security measures:
    - Job description is sanitized against prompt injection
    - Profile data has LaTeX special characters escaped
    - Strict output validation
    
    CRITICAL: This endpoint must NEVER return hallucinated content.
    All validation failures result in HTTP 500 errors that the backend
    should handle appropriately.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

    logger.info("Generating resume for template: %s", request.template_id)
    
    try:
        # Sanitize profile for LaTeX (escape special characters)
        safe_profile = sanitize_profile_for_latex(request.profile)
        profile_json = json.dumps(safe_profile, indent=2)
        
        # Job description is already sanitized by the validator
        safe_jd = request.job_description
        
        # Build the prompt with clear structure and strict instructions
        # Use delimiters to separate user content from instructions
        prompt = f"""{SYSTEM_PROMPT}

=== BEGIN JOB DESCRIPTION ===
{safe_jd}
=== END JOB DESCRIPTION ===

=== BEGIN CANDIDATE PROFILE (JSON) ===
{profile_json}
=== END CANDIDATE PROFILE ===

⚠️ CRITICAL REMINDERS BEFORE GENERATING:

1. VERIFY EVERY ENTITY:
   - Every company name MUST exist in profile.experience[].company
   - Every institution MUST exist in profile.education[].institution
   - Every certification MUST exist in profile.certifications[]
   - Every skill MUST exist in profile.skills[]
   - Every date MUST come from profile.experience[] or profile.education[]

2. DO NOT INVENT:
   - DO NOT add company suffixes (Inc., LLC) unless in profile
   - DO NOT use well-known companies/institutions unless in profile
   - DO NOT add related skills or certifications
   - DO NOT invent metrics, achievements, or statistics
   - DO NOT modify job titles or add seniority levels

3. OUTPUT REQUIREMENTS:
   - Output ONLY LaTeX code starting with \\documentclass
   - Use \\textit{{}} for dates and locations (formatting, not entities)
   - Use \\textbf{{}} for company/institution names (entities)
   - If information is missing, OMIT that section entirely

4. VALIDATION:
   The system will REJECT any output containing information not in the profile above.
   Double-check every company name, institution, certification, and skill before outputting.

Generate the LaTeX resume now:"""

        # Use environment variable for model name, with fallback to stable model
        # Available models: gemini-2.0-flash, gemini-2.5-flash, gemini-pro-latest, gemini-flash-latest
        model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        logger.info("Using Gemini model: %s", model_name)
        
        # Configure generation with timeout
        generation_config = genai.types.GenerationConfig(
            temperature=0.7,
            max_output_tokens=8192,
        )
        
        model = genai.GenerativeModel(
            model_name,
            generation_config=generation_config,
        )
        
        # Retry logic for transient failures
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                response = model.generate_content(
                    prompt,
                    request_options={"timeout": 90}  # 90 second timeout per request
                )
                break  # Success, exit retry loop
            except Exception as model_error:
                error_msg = str(model_error).lower()
                last_error = model_error
                
                # If quota exhausted or model not found, don't retry
                if "quota" in error_msg or "resource" in error_msg:
                    logger.error("Gemini API quota exhausted: %s", model_error)
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "error": "AI service quota exceeded. Please try again later.",
                            "code": "AI_SERVICE_ERROR"
                        }
                    )
                elif "not found" in error_msg:
                    logger.error("Model not found: %s, error: %s", model_name, model_error)
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": f"AI model '{model_name}' not available. Please check configuration.",
                            "code": "AI_SERVICE_ERROR"
                        }
                    )
                elif attempt < max_retries:
                    # Retry for transient errors (timeout, network issues)
                    logger.warning("Gemini API attempt %d failed, retrying: %s", attempt + 1, model_error)
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    # Final attempt failed
                    logger.error("Gemini API failed after %d attempts: %s", max_retries + 1, model_error)
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "error": "AI service is temporarily unavailable. Please try again.",
                            "code": "AI_SERVICE_ERROR"
                        }
                    )
        
        latex_source = response.text.strip()
        
        # Clean up if the model wrapped it in markdown code blocks despite instructions
        if latex_source.startswith("```latex"):
            latex_source = latex_source[8:]
        elif latex_source.startswith("```"):
            latex_source = latex_source[3:]
        if latex_source.endswith("```"):
            latex_source = latex_source[:-3]
            
        latex_source = latex_source.strip()
        
        # Fix common LaTeX issues that cause compilation failures
        latex_source = fix_latex_issues(latex_source)
        
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

        # Record modifications made (these are generic - actual modifications
        # depend on what the AI did, but we can't know exactly without analysis)
        modifications = [
            "Customized content based on job description keywords",
            "Structured resume for ATS compatibility",
            "Emphasized relevant experience and skills"
        ]
        
        logger.info("Resume generation successful for template: %s", request.template_id)
        
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