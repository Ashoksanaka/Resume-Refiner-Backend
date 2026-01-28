"""AI Agent Microservice for Resume AI Platform.

This service handles resume generation using Google's Gemini API.
It takes a user profile and job description, then generates complete LaTeX documents from scratch.

CRITICAL RULES:
- The AI GENERATES complete LaTeX documents (no templates are used)
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
    """Request model for resume generation.
    
    NOTE: The 'template' field is deprecated and no longer used.
    The AI now generates complete LaTeX documents from scratch.
    The field is kept for backward compatibility but is ignored.
    """
    profile: dict
    job_description: str
    template: str  # Deprecated: no longer used, kept for backward compatibility
    template_id: str  # Used for logging/identification only
    
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
    original_has_sections = bool(re.search(r'\\section\*?\{', original_latex))
    
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
        after_fix_has_sections = bool(re.search(r'\\section\*?\{', latex_source))
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
        original_body_has_sections = bool(re.search(r'\\section\*?\{', body))
        
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
        body_has_sections = bool(re.search(r'\\section\*?\{', body))
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
    Generate a complete resume LaTeX document using Gemini.
    
    The AI generates the entire LaTeX document from scratch - no templates are used.
    The output is a complete, compile-ready LaTeX document with ATS-friendly formatting.
    
    Security measures:
    - Job description is sanitized against prompt injection
    - Profile data has LaTeX special characters escaped
    - Strict output validation
    
    CRITICAL: This endpoint must NEVER return hallucinated content.
    All validation failures result in HTTP 500 errors that the backend
    should handle appropriately.
    
    NOTE: The 'template' field in the request is deprecated and ignored.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

    logger.info("[AI Agent Service] Generating resume for template: %s", request.template_id)
    logger.debug("[AI Agent Service] Request received - template_id: %s", request.template_id)
    
    try:
        # Sanitize profile for LaTeX (escape special characters)
        logger.info("[AI Agent Service] Sanitizing user profile for LaTeX (escaping special characters)")
        safe_profile = sanitize_profile_for_latex(request.profile)
        profile_json = json.dumps(safe_profile, indent=2)
        logger.info("[AI Agent Service] Profile sanitized. Profile JSON length: %d chars", len(profile_json))
        
        # Log profile structure
        profile_summary = {
            'has_experience': bool(safe_profile.get('experience')),
            'experience_count': len(safe_profile.get('experience', [])),
            'has_education': bool(safe_profile.get('education')),
            'education_count': len(safe_profile.get('education', [])),
            'has_skills': bool(safe_profile.get('skills')),
            'skills_count': len(safe_profile.get('skills', [])),
            'has_projects': bool(safe_profile.get('projects')),
            'projects_count': len(safe_profile.get('projects', [])),
        }
        logger.info("[AI Agent Service] Parsed user profile summary: %s", profile_summary)
        
        # Job description is already sanitized by the validator
        safe_jd = request.job_description
        logger.info("[AI Agent Service] Job description length: %d chars", len(safe_jd))
        
        # Build the prompt with clear structure and strict instructions
        # Use delimiters to separate user content from instructions
        # NOTE: Templates are no longer used - AI generates complete LaTeX from scratch
        logger.info("[AI Agent Service] Building prompt for Gemini API")
        logger.debug("[AI Agent Service] System prompt length: %d chars", len(SYSTEM_PROMPT))
        
        prompt = f"""{SYSTEM_PROMPT}

=== BEGIN JOB DESCRIPTION ===
{safe_jd}
=== END JOB DESCRIPTION ===

=== BEGIN CANDIDATE PROFILE (JSON) ===
{profile_json}
=== END CANDIDATE PROFILE ===

🚨🚨🚨 FINAL CRITICAL REMINDER BEFORE GENERATING 🚨🚨🚨

YOU ARE ABOUT TO GENERATE THE RESUME. FOLLOW THESE STEPS EXACTLY:

STEP 1: Generate the header (name and contact) ✓
STEP 2: CHECK profile.experience - If it has entries, ADD \section*{{Experience}} with ALL entries ✓
STEP 3: CHECK profile.education - If it has entries, ADD \section*{{Education}} with ALL entries ✓
STEP 4: CHECK profile.skills - If it has entries, ADD \section*{{Skills}} with ALL skills ✓
STEP 5: CHECK profile.projects - If it has entries, ADD \section*{{Projects}} with ALL projects ✓
STEP 6: Add other sections as needed (Certifications, Awards, etc.) ✓
STEP 7: Close with \end{{document}} ✓

⚠️ DO NOT STOP AFTER STEP 1 ⚠️
⚠️ DO NOT GENERATE ONLY THE HEADER ⚠️
⚠️ DO NOT STOP AFTER \end{{center}} ⚠️
⚠️ YOU MUST COMPLETE ALL STEPS ⚠️
⚠️ CONTINUE GENERATING UNTIL YOU REACH \end{{document}} ⚠️

A resume with only the header will be IMMEDIATELY REJECTED by the system.
You MUST include Experience, Education, Skills sections if they exist in the profile.
Your output MUST be at least 1000+ characters long to be considered complete.
Keep generating LaTeX code until you have written \end{{document}}.

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

3. LATEX COMMAND VALIDATION - CRITICAL:
   ⚠️ The system validates ALL LaTeX commands. Undefined commands will cause REJECTION.
   
   ✅ USE ONLY STANDARD COMMANDS:
   - Sections: \\section*{{...}}, \\subsection*{{...}} (WITH asterisk)
   - Formatting: \\textbf{{...}}, \\textit{{...}}, \\emph{{...}}
   - Lists: \\begin{{itemize}}, \\end{{itemize}}, \\item
   - Spacing: \\vspace{{...}}, \\hspace{{...}}, \\newline
   - Headers: \\textbf{{\\Large Name}} or \\textbf{{\\Huge Name}}
   
   ❌ DO NOT USE THESE (Will FAIL Validation):
   - Section commands: \\sectiontitle, \\sectionTitle, \\resumesection, \\customsection
   - Header commands: \\resumetitle, \\headertitle, \\nameformat, \\contactinfo
   - List commands: \\resumelist, \\bulletlist, \\customitemize
   - Item commands: \\experienceitem, \\educationitem, \\projectitem
   - Formatting commands: \\boldtext, \\italictext, \\underlinetext
   - Package commands: \\titleformat, \\titlespacing (titlesec forbidden)
   - Package commands: \\faPhone, \\faEnvelope (fontawesome5 not loaded)
   - Template commands: \\resumeItem, \\FullName (only in specific templates)
   - Any invented command names → Use standard LaTeX commands only
   
   🔍 RED FLAGS - If command contains these, DON'T USE IT:
   - "resume", "Resume", "custom", "Custom" at start
   - "title", "Title", "heading", "Heading" at end
   - "item", "Item", "list", "List" at end (except standard \\item)
   - Mixed case like "SectionTitle", "ResumeItem" (LaTeX uses lowercase)
   
   💡 REMEMBER: If you're not sure a command exists, DON'T use it. Use standard commands instead.
   💡 REMEMBER: Commands with "creative" names are ALWAYS wrong - use standard LaTeX.
   💡 REMEMBER: Every undefined command will cause the entire generation to FAIL.
   💡 REMEMBER: Math mode delimiters ($ and $$) MUST be balanced - every opening needs a closing.
   💡 REMEMBER: Avoid math mode in resumes unless absolutely necessary - use text formatting instead.

4. OUTPUT REQUIREMENTS:
   - Output ONLY LaTeX code starting with \\documentclass
   - Use \\textit{{}} for dates and locations (formatting, not entities)
   - Use \\textbf{{}} for company/institution names (entities)
   - Use \\section*{{...}} for section headings (NOT \\sectiontitle)
   - CRITICAL: Include ALL sections that have data in the profile
   - CRITICAL: The document must be COMPLETE - include Experience, Education, Skills sections
   - CRITICAL: DO NOT generate only the header - include full resume content
   - If a section has NO data, OMIT that section entirely
   - If a section HAS data, you MUST include it with ALL entries
   - Every \\begin{{itemize}} MUST have at least one \\item before \\end{{itemize}}

5. VALIDATION:
   The system will REJECT any output containing:
   - Information not in the profile above
   - Undefined LaTeX commands (like \\sectiontitle)
   - Empty list environments
   Double-check every company name, institution, certification, skill, AND LaTeX command before outputting.

Generate the LaTeX resume now:"""
        
        # Log prompt summary for debugging
        logger.info("[AI Agent Service] Prompt summary - System prompt: %d chars, JD: %d chars, Profile JSON: %d chars, Total: %d chars", 
                   len(SYSTEM_PROMPT), len(safe_jd), len(profile_json), len(prompt))
        logger.debug("[AI Agent Service] Profile JSON preview (first 500 chars): %s", profile_json[:500])
        logger.debug("[AI Agent Service] Profile JSON preview (last 500 chars): %s", profile_json[-500:] if len(profile_json) > 500 else profile_json)
        
        # Verify profile data contains expected sections
        if 'experience' in safe_profile and safe_profile['experience']:
            logger.info("[AI Agent Service] Profile contains %d experience entries", len(safe_profile['experience']))
            logger.debug("[AI Agent Service] First experience entry: %s", str(safe_profile['experience'][0])[:200])
        if 'education' in safe_profile and safe_profile['education']:
            logger.info("[AI Agent Service] Profile contains %d education entries", len(safe_profile['education']))
        if 'skills' in safe_profile and safe_profile['skills']:
            logger.info("[AI Agent Service] Profile contains %d skills", len(safe_profile['skills']))
            logger.debug("[AI Agent Service] Skills list: %s", str(safe_profile['skills'])[:200])

        # Use environment variable for model name, with fallback to stable model
        # Available models: gemini-2.0-flash, gemini-2.5-flash, gemini-pro-latest, gemini-flash-latest
        model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        logger.info("Using Gemini model: %s", model_name)
        
        # Configure generation with timeout
        # Increase max_output_tokens to ensure complete resumes are generated
        generation_config = genai.types.GenerationConfig(
            temperature=0.7,
            max_output_tokens=16384,  # Increased from 8192 to allow longer resumes
            top_p=0.95,
            top_k=40,
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
                logger.info("[AI Agent Service] Calling Gemini API (attempt %d/%d)", attempt + 1, max_retries + 1)
                response = model.generate_content(
                    prompt,
                    request_options={"timeout": 150}  # Increased timeout to 150 seconds (allows for Gemini API latency + processing)
                )
                
                # Check if response was cut off (incomplete)
                if hasattr(response, 'candidates') and response.candidates:
                    finish_reason = response.candidates[0].finish_reason if response.candidates else None
                    if finish_reason == 'MAX_TOKENS':
                        logger.warning("[AI Agent Service] Response was cut off due to token limit. Retrying with continuation...")
                        # If cut off, try to continue
                        if attempt < max_retries:
                            continue
                
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
        logger.info("[AI Agent Service] Received raw response from Gemini (length: %d chars)", len(latex_source))
        
        # Log a sample of the raw response to see what Gemini actually generated
        logger.info("[AI Agent Service] Raw response preview (first 1000 chars): %s", latex_source[:1000])
        logger.info("[AI Agent Service] Raw response preview (last 500 chars): %s", latex_source[-500:] if len(latex_source) > 500 else latex_source)
        
        # Check if response was cut off or incomplete
        if hasattr(response, 'candidates') and response.candidates:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None
            logger.info("[AI Agent Service] Response finish reason: %s", finish_reason)
            if finish_reason == 'MAX_TOKENS':
                logger.warning("[AI Agent Service] Response was truncated due to token limit")
        
        # Check body content in RAW response BEFORE any cleanup
        raw_body_start = latex_source.find('\\begin{document}')
        raw_body_end = latex_source.find('\\end{document}')
        if raw_body_start != -1 and raw_body_end != -1:
            raw_body = latex_source[raw_body_start:raw_body_end]
            raw_body_no_ws = re.sub(r'\s+', '', raw_body)
            raw_has_sections = bool(re.search(r'\\section\*?\{', raw_body))
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
            cleaned_has_sections = bool(re.search(r'\\section\*?\{', cleaned_body))
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
                    restored_has_sections = bool(re.search(r'\\section\*?\{', restored_body))
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
            has_sections = bool(re.search(r'\\section\*?\{', body_content))
            
            logger.info("[AI Agent Service] Body content check AFTER fixes - Length: %d chars, Has sections: %s", 
                       len(body_no_ws), has_sections)
            
            # If body is very short and has no sections, try to request continuation
            if len(body_no_ws) < 300 and not has_sections:
                logger.warning("[AI Agent Service] Output appears incomplete AFTER fixes - body too short and no sections detected")
                logger.warning("[AI Agent Service] Body preview: %s", body_content[:500])
                
                # Try to continue generation by requesting the AI to complete the document
                logger.info("[AI Agent Service] Attempting to request continuation from AI")
                continuation_prompt = f"""The LaTeX document you generated is incomplete. It only contains the header (name and contact information).

You MUST continue and add the following sections based on the profile data:
- Experience section (if profile.experience exists)
- Education section (if profile.education exists)  
- Skills section (if profile.skills exists)
- Projects section (if profile.projects exists)

Continue from where you left off. Add the missing sections and close with \\end{{document}}.

Current incomplete LaTeX:
{latex_source[-500:]}

Continue generating the complete LaTeX resume:"""
                
                try:
                    logger.info("[AI Agent Service] Requesting continuation from Gemini API")
                    continuation_response = model.generate_content(
                        continuation_prompt,
                        request_options={"timeout": 150}  # Match main request timeout
                    )
                    continuation_text = continuation_response.text.strip()
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
        
        # CRITICAL VALIDATION: Check if document has actual content sections
        # The document should not be just header - it must have sections
        body_start = latex_source.find('\\begin{document}')
        body_end = latex_source.find('\\end{document}')
        if body_start != -1 and body_end != -1:
            body_content = latex_source[body_start:body_end]
            # Check if body has section commands (Experience, Education, Skills, etc.)
            # Use raw string and properly escape backslashes for regex
            has_sections = bool(re.search(r'\\section\*?\{', body_content))
            
            # Also check for common section names in the content
            # Sometimes sections might be formatted differently, so check for keywords
            has_experience = bool(re.search(r'(?i)(experience|work\s+history|employment)', body_content))
            has_education = bool(re.search(r'(?i)(education|academic)', body_content))
            has_skills = bool(re.search(r'(?i)(skills?|technical\s+skills?)', body_content))
            has_projects = bool(re.search(r'(?i)(projects?)', body_content))
            has_any_content_section = has_experience or has_education or has_skills or has_projects
            
            # Count non-whitespace content
            body_no_whitespace = re.sub(r'\s+', '', body_content)
            
            # Check if sections have actual content (not just empty headers)
            # Look for \item commands or substantial text content after section headers
            has_list_items = bool(re.search(r'\\item', body_content))
            # Count content after removing common header patterns
            # Remove center environment content (name/contact) to check if there's more
            content_after_header = re.sub(r'\\begin\{center\}.*?\\end\{center\}', '', body_content, flags=re.DOTALL)
            content_after_header_no_ws = re.sub(r'\s+', '', content_after_header)
            
            # STRICT VALIDATION: Require sections to be present AND have content
            # A complete resume must have at least one content section with actual data
            if not has_sections and not has_any_content_section:
                logger.error("AI output appears incomplete - missing content sections")
                logger.error("Body length: %d, Has sections: %s, Has content keywords: %s", 
                           len(body_no_whitespace), has_sections, has_any_content_section)
                logger.error("Body preview (first 500 chars): %s", body_content[:500])
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "AI generated incomplete LaTeX document - missing content sections. Document must include Experience, Education, Skills, or other sections with actual content.",
                        "code": "MODEL_OUTPUT_INVALID"
                    }
                )
            
            # Check if sections exist but are empty (no items, no substantial content)
            if has_sections or has_any_content_section:
                if not has_list_items and len(content_after_header_no_ws) < 150:
                    logger.error("AI output has section headers but no content")
                    logger.error("Has list items: %s, Content after header length: %d", has_list_items, len(content_after_header_no_ws))
                    logger.error("Body preview (first 500 chars): %s", body_content[:500])
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": "AI generated incomplete LaTeX document - sections exist but contain no content. Document must include Experience, Education, Skills sections with actual entries (items, text, etc.).",
                            "code": "MODEL_OUTPUT_INVALID"
                        }
                    )
            
            # Also check if body is suspiciously short even with sections
            # A complete resume should have substantial content
            if len(body_no_whitespace) < 200:
                logger.warning("Body content is very short (%d chars), but sections detected. Continuing...", len(body_no_whitespace))

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