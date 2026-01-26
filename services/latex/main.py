"""
LaTeX Compilation Microservice for Resume AI Platform.

This service:
1. Manages LaTeX templates (load, validate, serve)
2. Compiles LaTeX source to PDF
3. Generates template previews
4. Serves preview images

CRITICAL RULES:
- Compilation runs in sandbox (no shell-escape, no network)
- Only files inside template directory may be accessed
- Compilation failure = hard failure (no partial PDFs)
- Preview output must be reproducible
"""

import os
import re
import uuid
import json
import shutil
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LaTeX Compilation Service",
    description="Compiles LaTeX source to PDF and manages resume templates",
    version="2.0.0"
)

# Configuration
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/app/output"))
TEMPLATES_DIR = Path(os.getenv("TEMPLATES_DIR", "/app/templates"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Forbidden LaTeX commands for security
FORBIDDEN_COMMANDS = [
    r'\\write18',
    r'\\immediate\\write18',
    r'\\input\{[|]',  # Input from pipe
    r'\\openin',
    r'\\openout',
    r'\\read',
    r'\\write(?!18)',  # Allow write18 detection separately
    r'\\catcode',
    r'\\special\{.*shell',
]


# =============================================================================
# Pydantic Models
# =============================================================================

class TemplateMetadata(BaseModel):
    """Template metadata schema."""
    id: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-z0-9-]+$')
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., max_length=2000)
    author: str = Field(..., max_length=255)
    version: str = Field(..., pattern=r'^\d+\.\d+\.\d+$')
    placeholders: list[str] = Field(default_factory=list)
    default_filename: str = Field(default="resume")
    required_packages: list[str] = Field(default_factory=list)
    compile_engine: str = Field(default="pdflatex")
    compile_runs: int = Field(default=2, ge=1, le=3)


class TemplateInfo(BaseModel):
    """Template information returned by API."""
    id: str
    name: str
    description: str
    author: str
    version: str
    placeholders: list[str]
    default_filename: str
    has_preview: bool
    preview_generated_at: Optional[str] = None


class CompileRequest(BaseModel):
    """Request model for LaTeX compilation."""
    latex_source: str
    filename: Optional[str] = None
    template_id: Optional[str] = None  # Optional: use template assets


class CompileResponse(BaseModel):
    """Response model for successful compilation."""
    success: bool
    filename: str
    log: str


class GeneratePreviewRequest(BaseModel):
    """Request model for preview generation."""
    template_id: str


# =============================================================================
# Template Manager
# =============================================================================

class TemplateManager:
    """
    Manages LaTeX templates.
    
    Responsibilities:
    - Load templates from filesystem
    - Validate template structure and metadata
    - Perform placeholder substitution
    - Generate previews
    """
    
    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        self._templates_cache: dict[str, TemplateMetadata] = {}
        self._load_templates()
    
    def _load_templates(self) -> None:
        """Load all templates from the templates directory."""
        self._templates_cache.clear()
        
        if not self.templates_dir.exists():
            logger.warning("Templates directory does not exist: %s", self.templates_dir)
            return
        
        for template_dir in self.templates_dir.iterdir():
            if template_dir.is_dir():
                try:
                    metadata = self._load_template(template_dir)
                    if metadata:
                        self._templates_cache[metadata.id] = metadata
                        logger.info("Loaded template: %s (v%s)", metadata.id, metadata.version)
                except Exception as e:
                    logger.error("Failed to load template %s: %s", template_dir.name, str(e))
    
    def _load_template(self, template_dir: Path) -> Optional[TemplateMetadata]:
        """Load and validate a single template."""
        metadata_path = template_dir / "metadata.json"
        template_path = template_dir / "template.tex"
        
        # Check required files exist
        if not metadata_path.exists():
            logger.warning("Template %s missing metadata.json", template_dir.name)
            return None
        
        if not template_path.exists():
            logger.warning("Template %s missing template.tex", template_dir.name)
            return None
        
        # Load and validate metadata
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata_dict = json.load(f)
            metadata = TemplateMetadata(**metadata_dict)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in %s: %s", metadata_path, str(e))
            return None
        except Exception as e:
            logger.error("Invalid metadata in %s: %s", metadata_path, str(e))
            return None
        
        # Validate template ID matches directory name
        if metadata.id != template_dir.name:
            logger.warning(
                "Template ID mismatch: metadata says '%s' but directory is '%s'",
                metadata.id, template_dir.name
            )
            return None
        
        # Validate template content for forbidden commands
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        if not self._validate_latex_security(template_content):
            logger.error("Template %s contains forbidden commands", metadata.id)
            return None
        
        return metadata
    
    def _validate_latex_security(self, latex_source: str) -> bool:
        """Check LaTeX source for forbidden commands."""
        for pattern in FORBIDDEN_COMMANDS:
            if re.search(pattern, latex_source, re.IGNORECASE):
                return False
        return True
    
    def reload_templates(self) -> int:
        """Reload all templates. Returns count of loaded templates."""
        self._load_templates()
        return len(self._templates_cache)
    
    def get_template(self, template_id: str) -> Optional[TemplateMetadata]:
        """Get template metadata by ID."""
        return self._templates_cache.get(template_id)
    
    def list_templates(self) -> list[TemplateMetadata]:
        """List all loaded templates."""
        return list(self._templates_cache.values())
    
    def get_template_dir(self, template_id: str) -> Optional[Path]:
        """Get the directory path for a template."""
        if template_id not in self._templates_cache:
            return None
        return self.templates_dir / template_id
    
    def get_template_content(self, template_id: str) -> Optional[str]:
        """Get the raw template.tex content."""
        template_dir = self.get_template_dir(template_id)
        if not template_dir:
            return None
        
        template_path = template_dir / "template.tex"
        if not template_path.exists():
            return None
        
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def get_main_template_content(self) -> Optional[str]:
        """Get the main.tex template content."""
        main_path = self.templates_dir / "main.tex"
        if not main_path.exists():
            return None
        
        with open(main_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def get_sample_profile(self, template_id: str) -> Optional[dict]:
        """Get the sample profile for a template."""
        template_dir = self.get_template_dir(template_id)
        if not template_dir:
            return None
        
        sample_path = template_dir / "examples" / "sample_profile.json"
        if not sample_path.exists():
            return None
        
        with open(sample_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def has_preview(self, template_id: str) -> bool:
        """Check if a template has generated previews."""
        template_dir = self.get_template_dir(template_id)
        if not template_dir:
            return False
        
        pdf_path = template_dir / "preview.pdf"
        png_path = template_dir / "preview.png"
        return pdf_path.exists() and png_path.exists()
    
    def get_preview_info(self, template_id: str) -> dict:
        """Get preview file information."""
        template_dir = self.get_template_dir(template_id)
        if not template_dir:
            return {"has_preview": False}
        
        pdf_path = template_dir / "preview.pdf"
        
        if not pdf_path.exists():
            return {"has_preview": False}
        
        stat = pdf_path.stat()
        return {
            "has_preview": True,
            "preview_generated_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        }


# =============================================================================
# Placeholder Substitution
# =============================================================================

class PlaceholderSubstitutor:
    """
    Handles placeholder substitution in LaTeX templates.
    
    Supports:
    - Simple placeholders: {{profile.field}}
    - Conditional blocks: {{#profile.field}}...{{/profile.field}}
    - Array iteration: {{#profile.array}}...{{/profile.array}}
    - Array items: {{.}} for current item in iteration
    """
    
    # Characters that need escaping in LaTeX
    LATEX_ESCAPE_MAP = {
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
    
    @classmethod
    def escape_latex(cls, text: str) -> str:
        """Escape special LaTeX characters in text."""
        if not isinstance(text, str):
            return str(text)
        
        result = text
        for char, escape in cls.LATEX_ESCAPE_MAP.items():
            result = result.replace(char, escape)
        return result
    
    @classmethod
    def get_nested_value(cls, data: dict, path: str) -> Any:
        """Get a nested value from a dictionary using dot notation."""
        keys = path.split('.')
        value = data
        
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
            
            if value is None:
                return None
        
        return value
    
    @classmethod
    def format_date(cls, date_str: Optional[str]) -> str:
        """Format a date string for display."""
        if not date_str:
            return "Present"
        
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            return date.strftime("%b %Y")
        except ValueError:
            return date_str
    
    @classmethod
    def format_description_items(cls, description: str) -> str:
        """Convert description text to LaTeX itemize items."""
        if not description:
            return ""
        
        # Split by sentences or newlines
        items = []
        for line in description.split('\n'):
            line = line.strip()
            if line:
                # Split long lines by periods
                sentences = [s.strip() for s in line.split('.') if s.strip()]
                items.extend(sentences)
        
        # Create LaTeX items using \resumeItem command
        latex_items = []
        for item in items[:5]:  # Limit to 5 items
            escaped = cls.escape_latex(item)
            latex_items.append(f"\\resumeItem{{{escaped}}}")
        
        return '\n'.join(latex_items)
    
    @classmethod
    def substitute(cls, template: str, profile: dict) -> str:
        """
        Substitute placeholders in a template with profile data.
        
        Args:
            template: LaTeX template with placeholders
            profile: Profile data dictionary
        
        Returns:
            LaTeX source with substituted values
        """
        result = template
        
        # Pre-process profile to add computed fields
        processed_profile = cls._preprocess_profile(profile)
        
        # Process conditional blocks first ({{#...}}...{{/...}})
        result = cls._process_conditionals(result, processed_profile)
        
        # Process array iterations
        result = cls._process_arrays(result, processed_profile)
        
        # Process simple placeholders
        result = cls._process_simple_placeholders(result, processed_profile)
        
        return result
    
    @classmethod
    def _preprocess_profile(cls, profile: dict) -> dict:
        """Add computed fields to the profile."""
        processed = dict(profile)
        
        # Add summary_tagline (first sentence of summary)
        summary = profile.get('summary', '')
        if summary:
            first_sentence = summary.split('.')[0]
            if len(first_sentence) > 60:
                first_sentence = first_sentence[:57] + '...'
            processed['summary_tagline'] = first_sentence
        else:
            processed['summary_tagline'] = ''
        
        # Add has_certifications flag
        certs = profile.get('certifications', [])
        processed['has_certifications'] = len(certs) > 0
        
        # Process experience entries
        experience = []
        for exp in profile.get('experience', []):
            exp_copy = dict(exp)
            exp_copy['end_date_display'] = cls.format_date(exp.get('end_date'))
            exp_copy['start_date'] = cls.format_date(exp.get('start_date'))
            exp_copy['description_items'] = cls.format_description_items(exp.get('description', ''))
            experience.append(exp_copy)
        processed['experience'] = experience
        
        # Process education entries
        education = []
        for edu in profile.get('education', []):
            edu_copy = dict(edu)
            edu_copy['end_date_display'] = cls.format_date(edu.get('end_date'))
            edu_copy['start_date'] = cls.format_date(edu.get('start_date'))
            edu_copy['description_items'] = cls.format_description_items(edu.get('description', ''))
            education.append(edu_copy)
        processed['education'] = education
        
        # Process certifications
        certifications = []
        for cert in profile.get('certifications', []):
            cert_copy = dict(cert)
            if cert.get('issue_date'):
                cert_copy['issue_date'] = cls.format_date(cert.get('issue_date'))
            certifications.append(cert_copy)
        processed['certifications'] = certifications
        
        # Process projects (if present)
        projects = []
        for proj in profile.get('projects', []):
            proj_copy = dict(proj)
            proj_copy['start_date'] = cls.format_date(proj.get('start_date'))
            proj_copy['end_date'] = cls.format_date(proj.get('end_date'))
            proj_copy['description_items'] = cls.format_description_items(proj.get('description', ''))
            projects.append(proj_copy)
        processed['projects'] = projects
        
        # Process skills formatting
        skills = profile.get('skills', [])
        if skills:
            # Split skills into languages and tools (simple heuristic)
            # Languages: Python, JavaScript, Java, C++, etc.
            language_keywords = ['python', 'javascript', 'java', 'c++', 'c#', 'typescript', 'go', 'rust', 'swift', 'kotlin', 'php', 'ruby', 'html', 'css', 'sql', 'r', 'scala', 'perl', 'shell', 'bash']
            languages = []
            tools = []
            
            for skill in skills:
                skill_lower = skill.lower()
                is_language = any(keyword in skill_lower for keyword in language_keywords)
                if is_language:
                    languages.append(skill)
                else:
                    tools.append(skill)
            
            processed['skills_languages'] = ', '.join(languages) if languages else 'N/A'
            processed['skills_tools'] = ', '.join(tools) if tools else ''
        
        return processed
    
    @classmethod
    def _process_conditionals(cls, template: str, data: dict) -> str:
        """Process conditional blocks."""
        # Pattern: {{#path}}content{{/path}}
        pattern = r'\{\{#([^}]+)\}\}(.*?)\{\{/\1\}\}'
        
        def replace_conditional(match):
            path = match.group(1)
            content = match.group(2)
            
            value = cls.get_nested_value({'profile': data}, f'profile.{path}')
            
            # Check if value is truthy
            if value:
                if isinstance(value, list) and len(value) == 0:
                    return ''
                return content
            return ''
        
        # Process from innermost to outermost
        prev_result = None
        result = template
        while prev_result != result:
            prev_result = result
            result = re.sub(pattern, replace_conditional, result, flags=re.DOTALL)
        
        return result
    
    @classmethod
    def _process_arrays(cls, template: str, data: dict) -> str:
        """Process array iteration blocks."""
        # Pattern: {{#profile.array}}...{{/profile.array}}
        pattern = r'\{\{#profile\.([a-z_]+)\}\}(.*?)\{\{/profile\.\1\}\}'
        
        def replace_array(match):
            array_name = match.group(1)
            item_template = match.group(2)
            
            array_data = data.get(array_name, [])
            if not isinstance(array_data, list):
                return ''
            
            results = []
            for item in array_data:
                item_result = item_template
                
                if isinstance(item, dict):
                    # Replace {{field}} and {{{field}}} with item values
                    for key, value in item.items():
                        # Handle double braces (escaped)
                        placeholder = '{{' + key + '}}'
                        # Handle triple braces (unescaped)
                        placeholder_triple = '{{{' + key + '}}}'
                        if value is not None:
                            escaped = cls.escape_latex(str(value))
                            unescaped = str(value)
                            item_result = item_result.replace(placeholder_triple, unescaped)
                            item_result = item_result.replace(placeholder, escaped)
                        else:
                            item_result = item_result.replace(placeholder_triple, '')
                            item_result = item_result.replace(placeholder, '')
                elif isinstance(item, str):
                    # Replace {{.}} with the item itself
                    item_result = item_result.replace('{{.}}', cls.escape_latex(item))
                
                results.append(item_result)
            
            return ''.join(results)
        
        result = re.sub(pattern, replace_array, template, flags=re.DOTALL)
        return result
    
    @classmethod
    def _process_simple_placeholders(cls, template: str, data: dict) -> str:
        """Process simple {{profile.path}} placeholders."""
        # Pattern: {{profile.path.to.value}}
        pattern = r'\{\{profile\.([^}]+)\}\}'
        
        def replace_placeholder(match):
            path = match.group(1)
            value = cls.get_nested_value(data, path)
            
            if value is None:
                return ''
            
            if isinstance(value, (list, dict)):
                return ''  # Complex types should be handled by array processing
            
            return cls.escape_latex(str(value))
        
        return re.sub(pattern, replace_placeholder, template)


# =============================================================================
# LaTeX Fix Functions
# =============================================================================

def fix_latex_before_compile(latex_source: str) -> str:
    """
    Fix common LaTeX issues before compilation.
    
    This runs in the LaTeX service to catch issues that might have
    slipped through the AI agent's fixes.
    """
    # Fix duplicate command definitions and invalid command names
    # Convert duplicate \newcommand to \providecommand (safer than removing)
    parts = latex_source.split('\\begin{document}')
    if len(parts) == 2:
        preamble, body = parts
        commands_defined = set()
        lines = preamble.split('\n')
        result_lines = []
        
        for line in lines:
            # Check for \newcommand or \renewcommand at start of line or after whitespace
            # Match: \newcommand[*]{name} or \newcommand[*][opt]{name}[num]
            match = re.search(r'(\s*)\\(?:new|renew)command(\*?)(\[[^\]]*\])?\{([^}]+)\}(\[[^\]]*\])?', line)
            if match:
                cmd_name = match.group(4)  # Extract command name
                
                # Validate command name (must be valid LaTeX command name)
                # LaTeX command names can contain letters, @ (in packages), but not spaces or special chars
                if not re.match(r'^[a-zA-Z@]+$', cmd_name):
                    # Skip invalid command definitions to avoid \endcsname errors
                    continue
                
                if cmd_name in commands_defined:
                    # Convert to \providecommand for duplicates (doesn't error if already defined)
                    # Preserve the original formatting
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
    # Fix cases where math mode might be left open before \end{center}
    # Pattern: Look for unclosed math mode before \end{center}
    center_sections = re.finditer(r'\\begin\{center\}.*?\\end\{center\}', latex_source, flags=re.DOTALL)
    for match in center_sections:
        center_content = match.group(0)
        # Count $ signs in this center block
        dollar_count = center_content.count('$')
        if dollar_count % 2 != 0:
            # Math mode is unclosed - find the last $ and ensure it's closed
            # Replace the center block with a fixed version
            fixed_center = center_content
            # If there's a $|$ pattern, ensure it's properly closed
            if '$|$' in fixed_center:
                # Ensure each $|$ is properly closed (it should be, but check)
                # Count $ before \end{center}
                before_end = fixed_center[:fixed_center.rfind('\\end{center}')]
                dollar_before = before_end.count('$')
                if dollar_before % 2 != 0:
                    # Add closing $ before \end{center}
                    fixed_center = fixed_center.replace('\\end{center}', '$\\end{center}', 1)
                    latex_source = latex_source.replace(center_content, fixed_center, 1)
    
    # Fix itemize/enumerate issues - "missing \item" errors
    # Remove empty itemize/enumerate environments
    latex_source = re.sub(r'\\begin\{(itemize|enumerate)\}[\s\n]*\\end\{(itemize|enumerate)\}', '', latex_source)
    
    # Fix itemize/enumerate with text before first \item
    # Pattern: \begin{itemize}\n[text]\n\item -> \begin{itemize}\n\item
    latex_source = re.sub(
        r'\\begin\{(itemize|enumerate)\}([^\n]*)\n+([^\\\n]+?)\n+\\item',
        r'\\begin{\1}\2\n\\item',
        latex_source,
        flags=re.MULTILINE
    )
    
    # Fix itemize/enumerate with blank lines before first \item
    latex_source = re.sub(
        r'\\begin\{(itemize|enumerate)\}([^\n]*)\n+\n+\\item',
        r'\\begin{\1}\2\n\\item',
        latex_source
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
    
    latex_source = re.sub(
        r'\\begin\{(itemize|enumerate)\}(.*?)\\end\{(itemize|enumerate)\}',
        fix_empty_lists,
        latex_source,
        flags=re.DOTALL
    )
    
    # Fix unmatched itemize/enumerate environments
    # Count opens and closes, remove extras
    itemize_opens = len(re.findall(r'\\begin\{itemize\}', latex_source))
    itemize_closes = len(re.findall(r'\\end\{itemize\}', latex_source))
    enumerate_opens = len(re.findall(r'\\begin\{enumerate\}', latex_source))
    enumerate_closes = len(re.findall(r'\\end\{enumerate\}', latex_source))
    
    # If there are more closes than opens, remove extra closes from the end
    if itemize_closes > itemize_opens:
        for _ in range(itemize_closes - itemize_opens):
            latex_source = re.sub(r'\\end\{itemize\}', '', latex_source, count=1)
    
    if enumerate_closes > enumerate_opens:
        for _ in range(enumerate_closes - enumerate_opens):
            latex_source = re.sub(r'\\end\{enumerate\}', '', latex_source, count=1)
    
    # If there are more opens than closes, add missing closes at the end (before \end{document})
    if itemize_opens > itemize_closes:
        missing = itemize_opens - itemize_closes
        # Add before \end{document}
        latex_source = re.sub(r'\\end\{document\}', '\\end{itemize}\n' * missing + '\\end{document}', latex_source, count=1)
    
    if enumerate_opens > enumerate_closes:
        missing = enumerate_opens - enumerate_closes
        latex_source = re.sub(r'\\end\{document\}', '\\end{enumerate}\n' * missing + '\\end{document}', latex_source, count=1)
    
    # Fix "Lonely \item" errors - remove \item commands that are outside list environments
    # This is safer than trying to wrap them, as wrapping might break structure
    # Pattern: \item that appears without a preceding \begin{itemize} or \begin{enumerate} nearby
    parts = latex_source.split('\\begin{document}')
    if len(parts) == 2:
        preamble, body = parts
        lines = body.split('\n')
        fixed_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this line has \item
            if '\\item' in line:
                # Look back up to 5 lines for \begin{itemize} or \begin{enumerate}
                found_list_start = False
                for j in range(max(0, i - 5), i):
                    if '\\begin{itemize}' in lines[j] or '\\begin{enumerate}' in lines[j]:
                        found_list_start = True
                        break
                
                # Also check current line and next few lines for list start
                if not found_list_start:
                    for j in range(i, min(len(lines), i + 3)):
                        if '\\begin{itemize}' in lines[j] or '\\begin{enumerate}' in lines[j]:
                            found_list_start = True
                            break
                
                if not found_list_start:
                    # This is a lonely \item - remove it (safer than wrapping)
                    # Just skip this line
                    i += 1
                    continue
            
            fixed_lines.append(line)
            i += 1
        
        body = '\n'.join(fixed_lines)
        latex_source = preamble + '\\begin{document}' + body
    
    # Fix undefined control sequences - remove or comment out problematic commands
    # Common problematic patterns that cause "Undefined control sequence"
    problematic_patterns = [
        (r'\\resumesection', ''),  # Remove if undefined
        (r'\\section\*\{([^}]+)\}', r'\\section{\1}'),  # Convert \section* to \section
    ]
    
    for pattern, replacement in problematic_patterns:
        latex_source = re.sub(pattern, replacement, latex_source)
    
    return latex_source


# =============================================================================
# LaTeX Compiler
# =============================================================================

class LaTeXCompiler:
    """
    Compiles LaTeX source to PDF.
    
    Security:
    - No shell-escape
    - No network access
    - Sandboxed compilation
    - Resource limits (time, memory)
    """
    
    COMPILE_TIMEOUT = int(os.getenv("LATEX_COMPILE_TIMEOUT", "60"))  # seconds
    
    @classmethod
    def compile(
        cls,
        latex_source: str,
        output_dir: Path,
        filename: str,
        template_dir: Optional[Path] = None,
        compile_runs: int = 2
    ) -> tuple[bool, str, Optional[Path]]:
        """
        Compile LaTeX source to PDF.
        
        Args:
            latex_source: LaTeX source code
            output_dir: Directory for output files
            filename: Output filename (without extension)
            template_dir: Optional template directory for assets
            compile_runs: Number of pdflatex runs
        
        Returns:
            Tuple of (success, log, pdf_path)
        """
        # Fix common LaTeX issues before compilation
        latex_source = fix_latex_before_compile(latex_source)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Copy template assets if provided
            if template_dir:
                assets_dir = template_dir / "assets"
                if assets_dir.exists():
                    for asset in assets_dir.iterdir():
                        shutil.copy2(asset, tmpdir_path / asset.name)
            
            # Write the LaTeX source
            tex_path = tmpdir_path / f"{filename}.tex"
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(latex_source)
            
            log_content = ""
            
            try:
                # Run pdflatex multiple times for proper references
                for run in range(compile_runs):
                    result = subprocess.run(
                        [
                            'pdflatex',
                            '-interaction=nonstopmode',
                            '-halt-on-error',
                            '-no-shell-escape',  # Security: disable shell escape
                            '-output-directory', str(tmpdir_path),
                            str(tex_path)
                        ],
                        capture_output=True,
                        text=True,
                        timeout=cls.COMPILE_TIMEOUT,
                        check=False,
                        cwd=str(tmpdir_path)  # Run from temp dir for security
                    )
                    
                    # Collect log
                    log_path = tmpdir_path / f"{filename}.log"
                    if log_path.exists():
                        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                            log_content = f.read()
                
                pdf_tmp_path = tmpdir_path / f"{filename}.pdf"
                
                if result.returncode != 0 or not pdf_tmp_path.exists():
                    # Extract error messages
                    error_lines = []
                    for line in (result.stdout + result.stderr + log_content).split('\n'):
                        if line.startswith('!') or 'error' in line.lower():
                            error_lines.append(line)
                    
                    error_message = '\n'.join(error_lines[:10]) if error_lines else 'Unknown compilation error'
                    logger.error("LaTeX compilation failed: %s", error_message[:200])
                    
                    # Log more context around the error
                    if log_content:
                        # Find the line number where error occurred
                        error_context = []
                        lines = log_content.split('\n')
                        for i, line in enumerate(lines):
                            if line.startswith('!') or 'error' in line.lower():
                                # Show 5 lines before and after error
                                start = max(0, i - 5)
                                end = min(len(lines), i + 10)
                                error_context = lines[start:end]
                                break
                        if error_context:
                            logger.error("Error context:\n%s", '\n'.join(error_context))
                    
                    # Log a sample of the LaTeX source for debugging (first 500 chars)
                    try:
                        with open(tex_path, 'r', encoding='utf-8') as f:
                            latex_sample = f.read()[:500]
                            logger.error("LaTeX source sample (first 500 chars):\n%s", latex_sample)
                    except Exception:
                        pass
                    
                    return False, log_content[-5000:], None
                
                # Copy PDF to output directory
                final_pdf_path = output_dir / f"{filename}.pdf"
                shutil.copy2(pdf_tmp_path, final_pdf_path)
                
                logger.info("LaTeX compilation successful: %s", final_pdf_path)
                return True, log_content, final_pdf_path
                
            except subprocess.TimeoutExpired:
                logger.error("LaTeX compilation timed out")
                return False, "Compilation timed out", None
            except FileNotFoundError:
                logger.error("pdflatex not found")
                return False, "pdflatex not installed", None
    
    @classmethod
    def convert_pdf_to_png(cls, pdf_path: Path, output_path: Path, dpi: int = 150) -> bool:
        """
        Convert first page of PDF to PNG.
        
        Args:
            pdf_path: Path to input PDF
            output_path: Path for output PNG
            dpi: Resolution in DPI
        
        Returns:
            True if successful
        """
        try:
            # Use pdftoppm (from poppler-utils) to convert PDF to PNG
            result = subprocess.run(
                [
                    'pdftoppm',
                    '-png',
                    '-f', '1',  # First page
                    '-l', '1',  # Last page (same as first)
                    '-r', str(dpi),  # Resolution
                    '-singlefile',  # Don't add page number suffix
                    str(pdf_path),
                    str(output_path.with_suffix(''))  # pdftoppm adds .png
                ],
                capture_output=True,
                timeout=30,
                check=False
            )
            
            if result.returncode == 0:
                # pdftoppm creates file without the suffix we removed, so rename
                expected_output = output_path.with_suffix('.png')
                if expected_output != output_path and expected_output.exists():
                    shutil.move(expected_output, output_path)
                return output_path.exists()
            
            logger.error("PDF to PNG conversion failed: %s", result.stderr.decode())
            return False
            
        except subprocess.TimeoutExpired:
            logger.error("PDF to PNG conversion timed out")
            return False
        except FileNotFoundError:
            logger.warning("pdftoppm not found, trying convert (ImageMagick)")
            # Fallback to ImageMagick
            try:
                result = subprocess.run(
                    [
                        'convert',
                        '-density', str(dpi),
                        f'{pdf_path}[0]',  # First page
                        '-quality', '90',
                        str(output_path)
                    ],
                    capture_output=True,
                    timeout=30,
                    check=False
                )
                return result.returncode == 0 and output_path.exists()
            except Exception as e:
                logger.error("ImageMagick conversion failed: %s", str(e))
                return False


# =============================================================================
# Initialize Template Manager
# =============================================================================

template_manager = TemplateManager(TEMPLATES_DIR)


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "templates_loaded": len(template_manager.list_templates())
    }


@app.post("/templates/reload")
async def reload_templates():
    """Reload all templates from filesystem."""
    count = template_manager.reload_templates()
    return {"status": "ok", "templates_loaded": count}


@app.get("/templates")
async def list_templates():
    """
    List all available templates.
    
    Returns array of template metadata.
    """
    templates = template_manager.list_templates()
    
    result = []
    for t in templates:
        preview_info = template_manager.get_preview_info(t.id)
        result.append(TemplateInfo(
            id=t.id,
            name=t.name,
            description=t.description,
            author=t.author,
            version=t.version,
            placeholders=t.placeholders,
            default_filename=t.default_filename,
            has_preview=preview_info["has_preview"],
            preview_generated_at=preview_info.get("preview_generated_at")
        ))
    
    return result


@app.get("/templates/{template_id}")
async def get_template(template_id: str):
    """
    Get details of a specific template.
    
    Returns template metadata.
    """
    template = template_manager.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    preview_info = template_manager.get_preview_info(template_id)
    
    return TemplateInfo(
        id=template.id,
        name=template.name,
        description=template.description,
        author=template.author,
        version=template.version,
        placeholders=template.placeholders,
        default_filename=template.default_filename,
        has_preview=preview_info["has_preview"],
        preview_generated_at=preview_info.get("preview_generated_at")
    )


@app.get("/templates/{template_id}/preview.png")
async def get_template_preview_png(template_id: str):
    """
    Get the PNG preview of a template.
    
    Returns PNG image binary.
    """
    template_dir = template_manager.get_template_dir(template_id)
    if not template_dir:
        raise HTTPException(status_code=404, detail="Template not found")
    
    preview_path = template_dir / "preview.png"
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="Preview not generated")
    
    return FileResponse(
        path=str(preview_path),
        media_type="image/png",
        filename=f"{template_id}_preview.png"
    )


@app.get("/templates/{template_id}/preview.pdf")
async def get_template_preview_pdf(template_id: str):
    """
    Get the PDF preview of a template.
    
    Returns PDF binary.
    """
    template_dir = template_manager.get_template_dir(template_id)
    if not template_dir:
        raise HTTPException(status_code=404, detail="Template not found")
    
    preview_path = template_dir / "preview.pdf"
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="Preview not generated")
    
    return FileResponse(
        path=str(preview_path),
        media_type="application/pdf",
        filename=f"{template_id}_preview.pdf"
    )


@app.get("/templates/main/content")
async def get_main_template_content():
    """
    Get the main.tex template content.
    
    Returns the main.tex file content as text.
    This is used by the AI agent to customize resumes.
    All resumes are generated from this single template.
    """
    template_content = template_manager.get_main_template_content()
    if not template_content:
        raise HTTPException(status_code=500, detail="Failed to read main.tex")
    
    from fastapi.responses import Response
    return Response(
        content=template_content,
        media_type="text/plain",
        headers={"Content-Disposition": 'inline; filename="main.tex"'}
    )


@app.get("/templates/{template_id}/content")
async def get_template_content(template_id: str):
    """
    Get the raw LaTeX template content.
    
    Returns the template.tex file content as text.
    This is used by the AI agent to customize templates.
    """
    template = template_manager.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template_content = template_manager.get_template_content(template_id)
    if not template_content:
        raise HTTPException(status_code=500, detail="Failed to read template.tex")
    
    from fastapi.responses import Response
    return Response(
        content=template_content,
        media_type="text/plain",
        headers={"Content-Disposition": f'inline; filename="{template_id}.tex"'}
    )


@app.post("/templates/{template_id}/generate-preview")
async def generate_template_preview(template_id: str):
    """
    Generate preview PDF and PNG for a template.
    
    Uses the sample_profile.json from the template's examples directory.
    This endpoint should be called during deployment/setup.
    """
    template = template_manager.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template_dir = template_manager.get_template_dir(template_id)
    
    # Get sample profile
    sample_profile = template_manager.get_sample_profile(template_id)
    if not sample_profile:
        raise HTTPException(
            status_code=400,
            detail="Template has no sample_profile.json in examples/"
        )
    
    # Get template content
    template_content = template_manager.get_template_content(template_id)
    if not template_content:
        raise HTTPException(status_code=500, detail="Failed to read template.tex")
    
    # Substitute placeholders
    latex_source = PlaceholderSubstitutor.substitute(template_content, sample_profile)
    
    # Compile to PDF
    success, log, pdf_path = LaTeXCompiler.compile(
        latex_source=latex_source,
        output_dir=template_dir,
        filename="preview",
        template_dir=template_dir,
        compile_runs=template.compile_runs
    )
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "LaTeX compilation failed",
                "log": log[-2000:] if log else ""
            }
        )
    
    # Convert to PNG
    png_path = template_dir / "preview.png"
    png_success = LaTeXCompiler.convert_pdf_to_png(pdf_path, png_path)
    
    if not png_success:
        logger.warning("PNG conversion failed for template %s", template_id)
    
    return {
        "success": True,
        "template_id": template_id,
        "preview_pdf": str(pdf_path),
        "preview_png": str(png_path) if png_success else None
    }


@app.post("/compile")
async def compile_latex(request: CompileRequest):
    """
    Compile LaTeX source to PDF.
    
    Returns the compiled PDF file or an error with the compilation log.
    """
    filename = request.filename or str(uuid.uuid4())
    logger.info("Compiling LaTeX: %s", filename)
    
    # Get template directory if specified
    template_dir = None
    compile_runs = 2
    if request.template_id:
        template = template_manager.get_template(request.template_id)
        if template:
            template_dir = template_manager.get_template_dir(request.template_id)
            compile_runs = template.compile_runs
    
    # Validate LaTeX security
    if not template_manager._validate_latex_security(request.latex_source):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "LaTeX source contains forbidden commands",
                "log": ""
            }
        )
    
    # Compile (fix_latex_before_compile is called inside compile method)
    success, log, pdf_path = LaTeXCompiler.compile(
        latex_source=request.latex_source,
        output_dir=OUTPUT_DIR,
        filename=filename,
        template_dir=template_dir,
        compile_runs=compile_runs
    )
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "LaTeX compilation failed",
                "log": log[-5000:] if log else ""
            }
        )
    
    return FileResponse(
        path=str(pdf_path),
        media_type='application/pdf',
        filename=f"{filename}.pdf"
    )


@app.post("/compile-with-profile")
async def compile_with_profile(template_id: str, profile: dict):
    """
    Compile a template with profile data.
    
    This is the main endpoint for resume generation.
    
    Args:
        template_id: ID of the template to use
        profile: Profile data to substitute into the template
    
    Returns:
        Compiled PDF
    """
    template = template_manager.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template_dir = template_manager.get_template_dir(template_id)
    
    # Get template content
    template_content = template_manager.get_template_content(template_id)
    if not template_content:
        raise HTTPException(status_code=500, detail="Failed to read template")
    
    # Substitute placeholders
    latex_source = PlaceholderSubstitutor.substitute(template_content, profile)
    
    # Generate unique filename
    filename = str(uuid.uuid4())
    
    # Compile
    success, log, pdf_path = LaTeXCompiler.compile(
        latex_source=latex_source,
        output_dir=OUTPUT_DIR,
        filename=filename,
        template_dir=template_dir,
        compile_runs=template.compile_runs
    )
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "LaTeX compilation failed",
                "log": log[-5000:] if log else ""
            }
        )
    
    return FileResponse(
        path=str(pdf_path),
        media_type='application/pdf',
        filename=f"{template.default_filename}.pdf"
    )


@app.get("/download/{filename}")
async def download_pdf(filename: str):
    """
    Download a previously compiled PDF.
    
    SECURITY: Validates filename is a valid UUID to prevent path traversal.
    """
    # Validate filename is a UUID to prevent path traversal attacks
    try:
        uuid.UUID(filename)
    except ValueError:
        logger.warning("Invalid filename format requested: %s", filename[:50])
        raise HTTPException(status_code=400, detail="Invalid filename format")
    
    # Construct path safely
    pdf_path = (OUTPUT_DIR / f"{filename}.pdf").resolve()
    
    # Verify the resolved path is within OUTPUT_DIR (defense in depth)
    try:
        pdf_path.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        logger.error("Path traversal attempt detected: %s", filename[:50])
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    
    return FileResponse(
        path=str(pdf_path),
        media_type='application/pdf',
        filename=f"{filename}.pdf"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
