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

# Import validator
# Use absolute import since we're running as a script, not a package
from validator import latex_validator, ValidationErrorType

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
    def escape_latex(cls, text: str, max_length: Optional[int] = None) -> str:
        """
        Escape special LaTeX characters in text.
        
        Args:
            text: Text to escape
            max_length: Optional maximum length. If provided, text will be truncated
                       to avoid breaking macros or causing compilation issues.
        
        Returns:
            Escaped LaTeX-safe text
        """
        if not isinstance(text, str):
            text = str(text)
        
        # Truncate if too long (to avoid breaking macros)
        if max_length and len(text) > max_length:
            text = text[:max_length].rstrip() + '...'
        
        result = text
        # Escape in order - backslash first to avoid double-escaping
        for char, escape in sorted(cls.LATEX_ESCAPE_MAP.items(), key=lambda x: x[0] == '\\', reverse=True):
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
            
            # Truncate very long fields to avoid breaking LaTeX macros
            # Common fields that might be long: descriptions, summaries, etc.
            max_length = 5000  # Reasonable limit for LaTeX content
            return cls.escape_latex(str(value), max_length=max_length)
        
        return re.sub(pattern, replace_placeholder, template)


# =============================================================================
# LaTeX Fix Functions
# =============================================================================

def fix_latex_before_compile(latex_source: str) -> str:
    """
    Fix common LaTeX issues before compilation.
    
    This runs in the LaTeX service to catch issues that might have
    slipped through the AI agent's fixes.
    
    Auto-fixes are applied only when safe and deterministic.
    """
    original_source = latex_source
    
    # Ensure \begin{document} exists - if missing, add it
    if '\\begin{document}' not in latex_source:
        # Try to find where document should start (after \documentclass)
        docclass_match = re.search(r'\\documentclass[^\n]*', latex_source)
        if docclass_match:
            # Insert \begin{document} after documentclass and packages
            insert_pos = docclass_match.end()
            # Find end of preamble (last \usepackage or similar)
            preamble_end = latex_source.find('\\usepackage', insert_pos)
            if preamble_end == -1:
                preamble_end = insert_pos
            else:
                # Find last \usepackage
                while True:
                    next_pkg = latex_source.find('\\usepackage', preamble_end + 1)
                    if next_pkg == -1:
                        break
                    preamble_end = next_pkg
                # Find end of last package line
                next_newline = latex_source.find('\n', preamble_end)
                if next_newline != -1:
                    preamble_end = next_newline + 1
            
            latex_source = latex_source[:preamble_end] + '\n\\begin{document}\n' + latex_source[preamble_end:]
        else:
            # No documentclass - add minimal structure
            latex_source = '\\documentclass{article}\n\\begin{document}\n' + latex_source
    
    # Fix AI agent hallucinations: Convert \sectiontitle{...} to \section*{...}
    # The AI agent sometimes generates \sectiontitle which doesn't exist
    # Auto-fix: Replace with standard \section* command
    latex_source = re.sub(
        r'\\sectiontitle\{([^}]+)\}',
        r'\\section*{\1}',
        latex_source
    )
    latex_source = re.sub(
        r'\\sectionTitle\{([^}]+)\}',
        r'\\section*{\1}',
        latex_source
    )
    latex_source = re.sub(
        r'\\SectionTitle\{([^}]+)\}',
        r'\\section*{\1}',
        latex_source
    )
    
    # Ensure \begin{document} exists after all fixes above
    if '\\begin{document}' not in latex_source:
        # This shouldn't happen if the code above worked, but add it as a safety net
        docclass_match = re.search(r'\\documentclass[^\n]*', latex_source)
        if docclass_match:
            # Find end of preamble
            insert_pos = docclass_match.end()
            # Look for last \usepackage or other preamble commands
            preamble_end = max(
                latex_source.rfind('\\usepackage'),
                latex_source.rfind('\\RequirePackage'),
                latex_source.rfind('\\documentclass')
            )
            if preamble_end == -1:
                preamble_end = insert_pos
            else:
                # Find end of last preamble line
                next_newline = latex_source.find('\n', preamble_end)
                if next_newline != -1:
                    preamble_end = next_newline + 1
                else:
                    preamble_end = len(latex_source)
            latex_source = latex_source[:preamble_end] + '\n\\begin{document}\n' + latex_source[preamble_end:]
        else:
            latex_source = '\\documentclass{article}\n\\begin{document}\n' + latex_source
    
    # Fix duplicate command definitions and invalid command names
    # Convert duplicate \newcommand to \providecommand (safer than removing)
    parts = latex_source.split('\\begin{document}', 1)  # Split only on first occurrence
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
        # Ensure \end{document} exists in body
        if '\\end{document}' not in body:
            body = body + '\n\\end{document}'
        latex_source = preamble + '\\begin{document}' + body
    
    # CRITICAL FIX: Fix math mode imbalances ($ and $$)
    # LaTeX has two types of math mode:
    # - Inline math: $...$ (single dollar signs)
    # - Display math: $$...$$ (double dollar signs)
    # Both must be balanced
    
    def fix_math_mode(source):
        """
        Fix unbalanced math mode delimiters.
        
        LaTeX has two types of math mode:
        - Inline math: $...$ (single dollar signs)
        - Display math: $$...$$ (double dollar signs)
        Both must be balanced.
        """
        # Step 1: Handle display math ($$...$$) first
        # Count $$ pairs - they must be balanced
        double_dollar_count = source.count('$$')
        if double_dollar_count % 2 != 0:
            # Unbalanced display math - find where to add closing $$
            # Find all $$ positions to determine if we need to close
            double_dollar_positions = []
            pos = 0
            while True:
                pos = source.find('$$', pos)
                if pos == -1:
                    break
                double_dollar_positions.append(pos)
                pos += 2
            
            # If odd number of $$, we need to add a closing $$
            if len(double_dollar_positions) % 2 != 0:
                # Find the best place to add closing $$
                if '\\end{document}' in source:
                    end_doc_pos = source.rfind('\\end{document}')
                    # Check if there's already a $$ right before \end{document}
                    check_start = max(0, end_doc_pos - 2)
                    before_end = source[check_start:end_doc_pos]
                    if before_end != '$$':
                        # Insert $$ before \end{document}
                        source = source[:end_doc_pos] + '$$' + source[end_doc_pos:]
                else:
                    # No \end{document} - add $$ at the end
                    source = source + '$$'
            
            # Double-check: after fixing, count should be even
            # If still odd, add another $$ (safety net)
            if source.count('$$') % 2 != 0:
                if '\\end{document}' in source:
                    end_doc_pos = source.rfind('\\end{document}')
                    source = source[:end_doc_pos] + '$$' + source[end_doc_pos:]
                else:
                    source = source + '$$'
        
        # Step 2: Handle inline math ($...$) - but exclude $$ pairs
        # Use a placeholder to temporarily replace $$ so we can count single $ separately
        placeholder = '___DOUBLE_DOLLAR_PLACEHOLDER___'
        temp_source = source.replace('$$', placeholder)
        
        # Count single $ signs (not part of $$)
        single_dollar_count = temp_source.count('$')
        if single_dollar_count % 2 != 0:
            # Unbalanced inline math - add closing $ before \end{document} or \end{center}
            if '\\end{document}' in source:
                end_doc_pos = source.rfind('\\end{document}')
                # Check if there's already a $ right before \end{document}
                check_start = max(0, end_doc_pos - 1)
                before_end = source[check_start:end_doc_pos]
                if before_end != '$':
                    # Insert $ before \end{document}
                    source = source[:end_doc_pos] + '$' + source[end_doc_pos:]
            elif '\\end{center}' in source:
                # Add $ before \end{center}
                source = source.replace('\\end{center}', '$\\end{center}', 1)
            else:
                # Add $ at the end
                source = source + '$'
        
        # Restore $$ from placeholder (in case any were in the source)
        source = source.replace(placeholder, '$$')
        
        return source
    
    latex_source = fix_math_mode(latex_source)
    
    # Fix math mode issues - ensure $|$ separators are properly closed
    # Fix cases where math mode might be left open before \end{center}
    # Pattern: Look for unclosed math mode before \end{center}
    center_sections = re.finditer(r'\\begin\{center\}.*?\\end\{center\}', latex_source, flags=re.DOTALL)
    for match in center_sections:
        center_content = match.group(0)
        # Count $ signs in this center block (excluding $$ pairs)
        temp_center = center_content.replace('$$', '')
        dollar_count = temp_center.count('$')
        if dollar_count % 2 != 0:
            # Math mode is unclosed - find the last $ and ensure it's closed
            # Replace the center block with a fixed version
            fixed_center = center_content
            # If there's a $|$ pattern, ensure it's properly closed
            if '$|$' in fixed_center:
                # Ensure each $|$ is properly closed (it should be, but check)
                # Count $ before \end{center}
                before_end = fixed_center[:fixed_center.rfind('\\end{center}')]
                temp_before = before_end.replace('$$', '')
                dollar_before = temp_before.count('$')
                if dollar_before % 2 != 0:
                    # Add closing $ before \end{center}
                    fixed_center = fixed_center.replace('\\end{center}', '$\\end{center}', 1)
                    latex_source = latex_source.replace(center_content, fixed_center, 1)
    
    # Fix itemize/enumerate issues - "missing \item" errors
    # This must be done carefully to handle nested environments correctly
    
    # First, remove completely empty list environments (no content at all)
    # Handle various whitespace patterns
    latex_source = re.sub(
        r'\\begin\{(itemize|enumerate)\}[\s\n%]*\\end\{(itemize|enumerate)\}',
        '',
        latex_source,
        flags=re.MULTILINE
    )
    
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
    
    # CRITICAL FIX: Fix mismatched environment names FIRST (before other processing)
    # This prevents errors like \begin{itemize}...\end{tightitemize} or \begin{itemize}...\end{enumerate}
    def fix_mismatched_environments(source):
        """
        Fix mismatched begin/end environment names.
        
        This function ensures that every \\begin{env} is closed with \\end{env} (matching name).
        It handles:
        - Direct mismatches: \begin{itemize}...\end{enumerate}
        - Variant names: \begin{itemize}...\end{tightitemize}
        - All LaTeX environments, not just itemize/enumerate
        """
        # Find all begin/end pairs and fix mismatches
        # Pattern to match \begin{env}...\end{different_env}
        # Use non-greedy matching to handle nested environments correctly
        pattern = r'\\begin\{([^}]+)\}(.*?)\\end\{([^}]+)\}'
        
        def fix_match(match):
            begin_env = match.group(1)
            content = match.group(2)
            end_env = match.group(3)
            
            # If environments don't match, fix the end to match begin
            if begin_env != end_env:
                # Normalize common mismatches for list environments
                # Handle tightitemize, compactitemize, etc. -> itemize
                normalized_begin = begin_env
                normalized_end = end_env
                
                # Check if both are list-related environments
                begin_lower = begin_env.lower()
                end_lower = end_env.lower()
                
                if 'itemize' in begin_lower or 'itemize' in end_lower:
                    # Both are itemize variants - normalize to 'itemize'
                    normalized_begin = 'itemize'
                elif 'enumerate' in begin_lower or 'enumerate' in end_lower:
                    # Both are enumerate variants - normalize to 'enumerate'
                    normalized_begin = 'enumerate'
                elif 'description' in begin_lower or 'description' in end_lower:
                    # Both are description variants - normalize to 'description'
                    normalized_begin = 'description'
                
                # If normalization worked, use normalized name
                # Otherwise, use the begin environment name (most reliable)
                if normalized_begin != begin_env and ('itemize' in begin_lower or 'enumerate' in begin_lower or 'description' in begin_lower):
                    return f'\\begin{{{normalized_begin}}}{content}\\end{{{normalized_begin}}}'
                else:
                    # Use the begin environment name (most reliable)
                    return f'\\begin{{{begin_env}}}{content}\\end{{{begin_env}}}'
            
            return match.group(0)  # No change needed
        
        # Apply fix iteratively to handle nested cases
        # Process from innermost to outermost by using multiple passes
        max_iterations = 10
        for _ in range(max_iterations):
            old_source = source
            source = re.sub(pattern, fix_match, source, flags=re.DOTALL)
            if old_source == source:
                break
        
        return source
    
    # Apply environment mismatch fix first
    latex_source = fix_mismatched_environments(latex_source)
    
    # More comprehensive check: ensure every \begin{itemize} or \begin{enumerate} has at least one \item
    # This handles nested cases and various content patterns
    def fix_empty_lists(match):
        begin_env = match.group(1)  # Environment name from \begin
        content = match.group(2)
        end_env = match.group(3)   # Environment name from \end
        
        # CRITICAL: Fix mismatched environments immediately (safety check)
        if begin_env != end_env:
            # Replace the mismatched \end with the correct one
            return f'\\begin{{{begin_env}}}{content}\\end{{{begin_env}}}'
        
        # Remove comments and whitespace for checking
        content_clean = re.sub(r'%.*', '', content)  # Remove comments
        content_clean = content_clean.strip()  # Remove leading/trailing whitespace
        
        # Check if there's at least one \item (not inside a comment)
        # Look for \item that's not part of a comment
        has_item = False
        lines = content.split('\n')
        for line in lines:
            # Remove comment portion
            comment_pos = line.find('%')
            if comment_pos != -1:
                line = line[:comment_pos]
            if '\\item' in line:
                has_item = True
                break
        
        if not has_item and not content_clean:
            return ''  # Remove completely empty list
        elif not has_item:
            # Has content but no \item - this will cause "missing \item" error
            # CRITICAL: Don't remove the environment if it has substantial content
            # Only remove if content is very short (likely just whitespace/comments)
            if len(content_clean) < 50:
                # Very short content - safe to remove
                return content_clean if content_clean else ''
            else:
                # Substantial content but no \item - keep the environment structure
                # This might cause a compilation error, but it's better than losing content
                logger.warning("[fix_empty_lists] List environment has content (%d chars) but no \\item - keeping structure", len(content_clean))
                return match.group(0)  # Keep original - don't remove
        
        return match.group(0)  # Keep if it has items
    
    # Apply fix multiple times to handle nested cases
    # CRITICAL: Use capturing groups to ensure begin/end match
    # CRITICAL: Do NOT use DOTALL - it causes matches across section boundaries
    # Instead, split by sections first to avoid cross-boundary matches
    max_iterations = 10
    
    # Store original to detect content loss
    original_length = len(latex_source)
    original_has_sections = bool(re.search(r'\\section\*?\{', latex_source))
    
    for iteration in range(max_iterations):
        old_source = latex_source
        old_length = len(latex_source)
        
        # Split by sections to avoid matching across section boundaries
        section_pattern = r'(\\section\*?\{[^}]+\})'
        parts = re.split(section_pattern, latex_source)
        
        if len(parts) > 1:
            # Process each section separately
            processed_parts = []
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    # This is content between sections
                    if part.strip():
                        # Apply fix only within this section's content
                        part = re.sub(
                            r'\\begin\{((itemize|enumerate|description))\}(.*?)\\end\{((itemize|enumerate|description))\}',
                            fix_empty_lists,
                            part,
                            flags=re.MULTILINE  # Use MULTILINE instead of DOTALL
                        )
                    processed_parts.append(part)
                else:
                    # This is a section header - keep as-is
                    processed_parts.append(part)
            latex_source = ''.join(processed_parts)
        else:
            # No sections found, apply fix normally but be cautious
            latex_source = re.sub(
                r'\\begin\{((itemize|enumerate|description))\}(.*?)\\end\{((itemize|enumerate|description))\}',
                fix_empty_lists,
                latex_source,
                flags=re.MULTILINE  # Use MULTILINE instead of DOTALL
            )
        
        # Verify we didn't lose too much content
        if len(latex_source) < old_length * 0.7:
            logger.error("[fix_latex_before_compile] CRITICAL: fix_empty_lists removed too much content (%d -> %d chars) in iteration %d. Reverting.", 
                        old_length, len(latex_source), iteration)
            latex_source = old_source
            break
        
        # Verify sections are still present
        if original_has_sections:
            if not re.search(r'\\section\*?\{', latex_source):
                logger.error("[fix_latex_before_compile] CRITICAL: Sections were removed by fix_empty_lists in iteration %d. Reverting.", iteration)
                latex_source = old_source
                break
        
        # Stop if no more changes
        if old_source == latex_source:
            break
    
    # Final check: if we lost more than 30% of content, something went wrong
    if len(latex_source) < original_length * 0.7:
        logger.error("[fix_latex_before_compile] CRITICAL: Total content loss detected (%d -> %d chars). This indicates a serious bug.", 
                    original_length, len(latex_source))
    
    # Fix unmatched itemize/enumerate environments - SAFE AUTO-FIX
    # Only fix if imbalance is obvious and fixable (single missing brace/environment)
    itemize_opens = len(re.findall(r'\\begin\{itemize\}', latex_source))
    itemize_closes = len(re.findall(r'\\end\{itemize\}', latex_source))
    enumerate_opens = len(re.findall(r'\\begin\{enumerate\}', latex_source))
    enumerate_closes = len(re.findall(r'\\end\{enumerate\}', latex_source))
    
    # Only auto-fix if imbalance is small (1-2) to avoid inventing structure
    max_safe_imbalance = 2
    
    # If there are more closes than opens, remove extra closes from the end (safe)
    if itemize_closes > itemize_opens and (itemize_closes - itemize_opens) <= max_safe_imbalance:
        for _ in range(itemize_closes - itemize_opens):
            # Remove last occurrence
            parts = latex_source.rsplit('\\end{itemize}', 1)
            if len(parts) == 2:
                latex_source = parts[0] + parts[1]
    
    if enumerate_closes > enumerate_opens and (enumerate_closes - enumerate_opens) <= max_safe_imbalance:
        for _ in range(enumerate_closes - enumerate_opens):
            # Remove last occurrence
            parts = latex_source.rsplit('\\end{enumerate}', 1)
            if len(parts) == 2:
                latex_source = parts[0] + parts[1]
    
    # If there are more opens than closes, add missing closes at the end (before \end{document})
    # Only if imbalance is small and safe
    if itemize_opens > itemize_closes and (itemize_opens - itemize_closes) <= max_safe_imbalance:
        missing = itemize_opens - itemize_closes
        # Add before \end{document}
        if '\\end{document}' in latex_source:
            latex_source = latex_source.replace('\\end{document}', '\\end{itemize}\n' * missing + '\\end{document}', 1)
    
    if enumerate_opens > enumerate_closes and (enumerate_opens - enumerate_closes) <= max_safe_imbalance:
        missing = enumerate_opens - enumerate_closes
        if '\\end{document}' in latex_source:
            latex_source = latex_source.replace('\\end{document}', '\\end{enumerate}\n' * missing + '\\end{document}', 1)
    
    # Ensure \begin{document} still exists after all fixes
    if '\\begin{document}' not in latex_source:
        # Safety check - re-add if somehow removed
        docclass_match = re.search(r'\\documentclass[^\n]*', latex_source)
        if docclass_match:
            insert_pos = docclass_match.end()
            preamble_end = max(
                latex_source.rfind('\\usepackage'),
                latex_source.rfind('\\RequirePackage'),
                latex_source.rfind('\\documentclass')
            )
            if preamble_end == -1:
                preamble_end = insert_pos
            else:
                next_newline = latex_source.find('\n', preamble_end)
                if next_newline != -1:
                    preamble_end = next_newline + 1
                else:
                    preamble_end = len(latex_source)
            latex_source = latex_source[:preamble_end] + '\n\\begin{document}\n' + latex_source[preamble_end:]
        else:
            latex_source = '\\documentclass{article}\n\\begin{document}\n' + latex_source
    
    # Fix "Lonely \item" errors - SAFE AUTO-FIX
    # Try to wrap lonely \item commands in itemize environment if safe
    # Only wrap if there's a clear pattern (multiple items together)
    parts = latex_source.split('\\begin{document}', 1)  # Split only on first occurrence
    if len(parts) == 2:
        preamble, body = parts
        lines = body.split('\n')
        fixed_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this line has \item
            if '\\item' in line:
                # Look back up to 10 lines for \begin{itemize} or \begin{enumerate}
                found_list_start = False
                lookback_start = max(0, i - 10)
                for j in range(lookback_start, i):
                    if '\\begin{itemize}' in lines[j] or '\\begin{enumerate}' in lines[j] or '\\begin{description}' in lines[j]:
                        found_list_start = True
                        break
                
                # Also check if we're already inside a list (look for \end)
                if not found_list_start:
                    # Check if there's an \end before us
                    for j in range(lookback_start, i):
                        if '\\end{itemize}' in lines[j] or '\\end{enumerate}' in lines[j] or '\\end{description}' in lines[j]:
                            # Check if there's a begin after this end
                            has_begin_after = False
                            for k in range(j + 1, i):
                                if '\\begin{itemize}' in lines[k] or '\\begin{enumerate}' in lines[k] or '\\begin{description}' in lines[k]:
                                    found_list_start = True
                                    has_begin_after = True
                                    break
                            if not has_begin_after:
                                break
                
                if not found_list_start:
                    # Check if there are multiple \item commands nearby (safe to wrap)
                    item_count = 0
                    lookahead_end = min(len(lines), i + 5)
                    for j in range(i, lookahead_end):
                        if '\\item' in lines[j]:
                            item_count += 1
                    
                    # Only wrap if there are at least 2 items together (safer pattern)
                    if item_count >= 2:
                        # Wrap in itemize - insert \begin{itemize} before first item
                        # Check if we already inserted it
                        if i == 0 or '\\begin{itemize}' not in lines[i-1]:
                            fixed_lines.append('\\begin{itemize}')
                        fixed_lines.append(line)
                        # We'll close it later when we find non-item content
                    else:
                        # Single lonely item - remove it (safer than wrapping)
                        i += 1
                        continue
                else:
                    fixed_lines.append(line)
            else:
                # Not an item line
                # If we have open itemize and this is not an item, close it
                if fixed_lines and fixed_lines[-1].strip() and '\\item' not in line and '\\begin' not in line and '\\end' not in line:
                    # Check if last line was an item
                    if fixed_lines and '\\item' in fixed_lines[-1]:
                        # Check if we need to close itemize
                        # Look back to see if we opened one
                        for j in range(len(fixed_lines) - 1, max(0, len(fixed_lines) - 10), -1):
                            if '\\begin{itemize}' in fixed_lines[j]:
                                # Check if we haven't closed it
                                has_closed = False
                                for k in range(j + 1, len(fixed_lines)):
                                    if '\\end{itemize}' in fixed_lines[k]:
                                        has_closed = True
                                        break
                                if not has_closed:
                                    fixed_lines.append('\\end{itemize}')
                                break
                
                fixed_lines.append(line)
            i += 1
        
        # Close any open itemize at the end
        if fixed_lines:
            itemize_count = sum(1 for line in fixed_lines if '\\begin{itemize}' in line)
            itemize_end_count = sum(1 for line in fixed_lines if '\\end{itemize}' in line)
            if itemize_count > itemize_end_count:
                fixed_lines.append('\\end{itemize}')
        
        body = '\n'.join(fixed_lines)
        latex_source = preamble + '\\begin{document}' + body
    
    # Fix undefined control sequences - SAFE AUTO-FIX
    # Only fix known problematic patterns that are safe to replace
    problematic_patterns = [
        (r'\\resumesection', ''),  # Remove if undefined (safe - just removes command)
        (r'\\section\*\{([^}]+)\}', r'\\section{\1}'),  # Convert \section* to \section (safe)
    ]
    
    for pattern, replacement in problematic_patterns:
        latex_source = re.sub(pattern, replacement, latex_source)
    
    # Fix malformed \href commands that can cause "Too many }'s" errors
    # Pattern: \href{url}{text} - detect and fix truncated or malformed hrefs
    # Find \href commands that might be malformed (e.g., truncated URLs)
    href_pattern = r'\\href\{([^}]*)\}(\{([^}]*)\})?'
    
    def fix_malformed_href(match):
        url_part = match.group(1) or ''
        text_part = match.group(3) if match.group(2) else ''
        
        # If URL is truncated (ends with ...) or very long, it might be malformed
        # Check if URL has balanced braces
        url_open = url_part.count('{') - url_part.count('\\{')
        url_close = url_part.count('}') - url_part.count('\\}')
        
        # If URL has unbalanced braces or is truncated, replace with safe version
        if url_open != url_close or url_part.endswith('...') or len(url_part) > 500:
            # Replace malformed href with just the text (or URL if no text)
            return text_part if text_part else url_part[:100]  # Truncate to safe length
        
        # If we have both URL and text, validate the structure
        if text_part:
            # Both parts exist - check if structure is valid
            return match.group(0)  # Keep as-is if valid
        else:
            # Missing text part - add empty text to close the command
            return f'\\href{{{url_part}}}{{}}'
    
    latex_source = re.sub(href_pattern, fix_malformed_href, latex_source)
    
    # Fix simple bracket imbalances
    # Count braces and fix imbalances if small and safe
    open_braces = latex_source.count('{') - latex_source.count('\\{')
    close_braces = latex_source.count('}') - latex_source.count('\\}')
    brace_imbalance = open_braces - close_braces
    
    # Handle "Too many }'s" error - remove extra closing braces if safe
    if brace_imbalance < 0:
        # Too many closing braces - this is the "Too many }'s" error
        excess_closes = abs(brace_imbalance)
        if excess_closes <= 3:  # Only fix small excesses (1-3)
            # Remove excess closing braces from the end (before \end{document})
            if '\\end{document}' in latex_source:
                before_end = latex_source[:latex_source.rfind('\\end{document}')]
                removed = 0
                # Remove excess closing braces from right to left
                for i in range(len(before_end) - 1, -1, -1):
                    if before_end[i] == '}' and (i == 0 or before_end[i-1] != '\\'):
                        before_end = before_end[:i] + before_end[i+1:]
                        removed += 1
                        if removed >= excess_closes:
                            break
                latex_source = before_end + '\\end{document}'
    
    # Handle missing closing braces - add them if safe
    if 0 < brace_imbalance <= 2:
        # Add missing closing braces at the end (before \end{document})
        if '\\end{document}' in latex_source:
            latex_source = latex_source.replace('\\end{document}', '}' * brace_imbalance + '\\end{document}', 1)
    
    # Final safety check: ensure \begin{document} and \end{document} exist
    if '\\begin{document}' not in latex_source:
        # Last resort: add minimal document structure
        docclass_match = re.search(r'\\documentclass[^\n]*', latex_source)
        if docclass_match:
            insert_pos = docclass_match.end()
            # Find a good insertion point (after last preamble command)
            preamble_end = max(
                latex_source.rfind('\\usepackage'),
                latex_source.rfind('\\RequirePackage'),
                latex_source.rfind('\\documentclass'),
                latex_source.rfind('\n', 0, insert_pos + 500)
            )
            if preamble_end == -1:
                preamble_end = insert_pos
            else:
                next_newline = latex_source.find('\n', preamble_end)
                if next_newline != -1:
                    preamble_end = next_newline + 1
                else:
                    preamble_end = len(latex_source)
            latex_source = latex_source[:preamble_end] + '\n\\begin{document}\n' + latex_source[preamble_end:]
        else:
            latex_source = '\\documentclass{article}\n\\begin{document}\n' + latex_source
    
    # Ensure \end{document} exists (but only one)
    # Count occurrences
    begin_doc_count = latex_source.count('\\begin{document}')
    end_doc_count = latex_source.count('\\end{document}')
    
    # If there are multiple \begin{document} or \end{document}, keep only the first/last
    if begin_doc_count > 1:
        # Keep only the first \begin{document}
        first_begin = latex_source.find('\\begin{document}')
        if first_begin != -1:
            # Remove all other occurrences
            latex_source = latex_source[:first_begin+len('\\begin{document}')] + \
                          latex_source[first_begin+len('\\begin{document}'):].replace('\\begin{document}', '')
    
    if end_doc_count > 1:
        # Keep only the last \end{document}
        last_end = latex_source.rfind('\\end{document}')
        if last_end != -1:
            # Remove all other occurrences BEFORE the last one
            before_last = latex_source[:last_end]
            after_last = latex_source[last_end:]
            # Remove all \end{document} from before_last
            before_last = before_last.replace('\\end{document}', '')
            latex_source = before_last + after_last
            logger.warning("[fix_latex_before_compile] Removed %d duplicate \\end{document} tags (kept only the last one)", end_doc_count - 1)
    
    # Ensure \end{document} exists (only if missing)
    if '\\end{document}' not in latex_source:
        latex_source = latex_source + '\n\\end{document}'
    
    # Final pass: remove any remaining empty list environments and fix any remaining mismatches
    # This is a safety net after all other fixes
    def remove_empty_lists_final(match):
        begin_env = match.group(1)
        content = match.group(2)
        end_env = match.group(3)
        
        # CRITICAL: Fix any remaining mismatches
        if begin_env != end_env:
            return f'\\begin{{{begin_env}}}{content}\\end{{{begin_env}}}'
        
        # Remove comments and whitespace
        content_clean = re.sub(r'%.*', '', content).strip()
        # Check for \item
        if '\\item' not in content_clean:
            # Only remove if content is very short (likely empty)
            if len(content_clean) < 50:
                return ''
            else:
                # Substantial content - keep it even without \item
                logger.warning("[remove_empty_lists_final] List environment has content (%d chars) but no \\item - keeping structure", len(content_clean))
                return match.group(0)  # Keep original
        return match.group(0)
    
    # Final cleanup pass - also fixes mismatches
    # CRITICAL: Do NOT use DOTALL - split by sections first
    final_original_length = len(latex_source)
    for iteration in range(3):  # Multiple passes for nested cases
        old_source = latex_source
        old_length = len(latex_source)
        
        # Split by sections to avoid matching across section boundaries
        section_pattern = r'(\\section\*?\{[^}]+\})'
        parts = re.split(section_pattern, latex_source)
        
        if len(parts) > 1:
            # Process each section separately
            processed_parts = []
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    # This is content between sections
                    if part.strip():
                        # Apply fix only within this section's content
                        part = re.sub(
                            r'\\begin\{((itemize|enumerate|description))\}(.*?)\\end\{((itemize|enumerate|description))\}',
                            remove_empty_lists_final,
                            part,
                            flags=re.MULTILINE  # Use MULTILINE instead of DOTALL
                        )
                    processed_parts.append(part)
                else:
                    # This is a section header - keep as-is
                    processed_parts.append(part)
            latex_source = ''.join(processed_parts)
        else:
            # No sections found, apply fix normally
            latex_source = re.sub(
                r'\\begin\{((itemize|enumerate|description))\}(.*?)\\end\{((itemize|enumerate|description))\}',
                remove_empty_lists_final,
                latex_source,
                flags=re.MULTILINE  # Use MULTILINE instead of DOTALL
            )
        
        # Verify we didn't lose too much content
        if len(latex_source) < old_length * 0.7:
            logger.error("[fix_latex_before_compile] CRITICAL: remove_empty_lists_final removed too much content (%d -> %d chars) in iteration %d. Reverting.", 
                        old_length, len(latex_source), iteration)
            latex_source = old_source
            break
        
        if old_source == latex_source:
            break
    
    # Final check: if we lost more than 30% of content in final pass, something went wrong
    if len(latex_source) < final_original_length * 0.7:
        logger.error("[fix_latex_before_compile] CRITICAL: Final pass removed too much content (%d -> %d chars).", 
                    final_original_length, len(latex_source))
    
    # Final safety check: fix any remaining mismatched environments
    # This catches any that weren't caught by the above passes
    latex_source = fix_mismatched_environments(latex_source)
    
    # CRITICAL FIX: Close any unclosed environments before \end{document}
    # This prevents errors like "\begin{center} ended by \end{document}"
    # BUT: Only close if there's exactly ONE \end{document} (duplicate removal should have run first)
    def close_unclosed_environments(source):
        """Close any unclosed \begin{...} environments before \end{document}."""
        # CRITICAL: Only process if there's exactly one \end{document}
        end_doc_count = source.count('\\end{document}')
        if end_doc_count == 0:
            return source
        
        if end_doc_count > 1:
            logger.warning("[close_unclosed_environments] Multiple \\end{document} found (%d). Skipping environment closing to avoid corruption.", end_doc_count)
            return source
        
        # Find the single \end{document} position (use rfind to be safe)
        end_doc_pos = source.rfind('\\end{document}')
        if end_doc_pos == -1:
            return source
        
        # Only process content BEFORE the \end{document}
        content_before_end = source[:end_doc_pos]
        
        # Find all \begin{env} and \end{env} in content before \end{document}
        begin_pattern = r'\\begin\{([^}]+)\}'
        end_pattern = r'\\end\{([^}]+)\}'
        
        begins = []
        ends = []
        
        for match in re.finditer(begin_pattern, content_before_end):
            env_name = match.group(1)
            begins.append((env_name, match.start()))
        
        for match in re.finditer(end_pattern, content_before_end):
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
                    # Mismatch - try to match by popping from stack
                    found_match = False
                    for i in range(len(env_stack) - 1, -1, -1):
                        if env_stack[i] == env_name:
                            env_stack = env_stack[:i] + env_stack[i+1:]
                            found_match = True
                            break
                    if not found_match:
                        # Extra closing - ignore
                        pass
        
        # Close any remaining open environments before \end{document}
        if env_stack:
            # Build closing tags in reverse order (LIFO)
            closing_tags = []
            for env_name in reversed(env_stack):
                closing_tags.append(f'\\end{{{env_name}}}')
            
            # Insert closing tags before \end{document}
            closing_text = '\n' + '\n'.join(closing_tags) + '\n'
            source = source[:end_doc_pos] + closing_text + source[end_doc_pos:]
            logger.info("[close_unclosed_environments] Closed %d unclosed environments: %s", len(env_stack), env_stack)
        
        return source
    
    # CRITICAL: Run close_unclosed_environments AFTER duplicate removal
    latex_source = close_unclosed_environments(latex_source)
    
    # FINAL SAFETY CHECK: Fix math mode one more time at the end
    # This catches any math mode issues that might have been introduced by other fixes
    latex_source = fix_math_mode(latex_source)
    
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
        logger.info("[LaTeX Compiler] LaTeX source length BEFORE fixes: %d chars", len(latex_source))
        logger.info("[LaTeX Compiler] LaTeX source BEFORE fixes (first 3000 chars):\n%s", latex_source[:3000])
        latex_source = fix_latex_before_compile(latex_source)
        logger.info("[LaTeX Compiler] LaTeX source length AFTER fixes: %d chars", len(latex_source))
        
        # Log full LaTeX source for debugging (first 2000 and last 500 chars)
        logger.info("[LaTeX Compiler] LaTeX source preview (first 2000 chars):\n%s", latex_source[:2000])
        logger.info("[LaTeX Compiler] LaTeX source preview (last 500 chars):\n%s", latex_source[-500:] if len(latex_source) > 500 else latex_source)
        
        # Check for document structure
        has_begin_doc = '\\begin{document}' in latex_source
        has_end_doc = '\\end{document}' in latex_source
        begin_doc_count = latex_source.count('\\begin{document}')
        end_doc_count = latex_source.count('\\end{document}')
        logger.info("[LaTeX Compiler] Document structure check - begin{document}: %s (count: %d), end{document}: %s (count: %d)", 
                   has_begin_doc, begin_doc_count, has_end_doc, end_doc_count)
        
        # Check for sections
        section_count = len(re.findall(r'\\section\*?\{', latex_source))
        logger.info("[LaTeX Compiler] Found %d section commands in LaTeX source", section_count)
        
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
            logger.info("[LaTeX Compiler] Writing LaTeX source to: %s", tex_path)
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(latex_source)
            logger.info("[LaTeX Compiler] LaTeX source written successfully (%d bytes)", tex_path.stat().st_size)
            
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
                    logger.debug("[LaTeX Compiler] pdflatex run %d/%d completed (returncode: %d)", run + 1, compile_runs, result.returncode)
                    
                    # Log compilation output for debugging
                    if result.stdout:
                        # Extract important warnings/errors from stdout
                        stdout_lines = result.stdout.split('\n')
                        warnings = [line for line in stdout_lines if 'warning' in line.lower() or 'error' in line.lower() or 'overfull' in line.lower() or 'underfull' in line.lower()]
                        if warnings:
                            logger.warning("[LaTeX Compiler] pdflatex run %d/%d warnings/errors:\n%s", run + 1, compile_runs, '\n'.join(warnings[:20]))
                    
                    if result.stderr:
                        logger.error("[LaTeX Compiler] pdflatex run %d/%d stderr:\n%s", run + 1, compile_runs, result.stderr[:1000])
                    if log_path.exists():
                        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                            log_content = f.read()
                        logger.debug("[LaTeX Compiler] pdflatex run %d/%d completed (returncode: %d)", run + 1, compile_runs, result.returncode)
                    else:
                        logger.warning("[LaTeX Compiler] No log file found after pdflatex run %d/%d", run + 1, compile_runs)
                
                pdf_tmp_path = tmpdir_path / f"{filename}.pdf"
                logger.info("[LaTeX Compiler] Checking for compiled PDF: %s", pdf_tmp_path)
                
                if result.returncode != 0 or not pdf_tmp_path.exists():
                    # Extract error messages
                    logger.error("[LaTeX Compiler] Compilation failed (returncode: %d, PDF exists: %s)", 
                               result.returncode, pdf_tmp_path.exists())
                    error_lines = []
                    for line in (result.stdout + result.stderr + log_content).split('\n'):
                        if line.startswith('!') or 'error' in line.lower():
                            error_lines.append(line)
                    
                    error_message = '\n'.join(error_lines[:10]) if error_lines else 'Unknown compilation error'
                    logger.error("[LaTeX Compiler] LaTeX compilation failed: %s", error_message[:200])
                    
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
                logger.info("[LaTeX Compiler] Copying PDF from temp directory to output directory: %s", final_pdf_path)
                shutil.copy2(pdf_tmp_path, final_pdf_path)
                logger.info("[LaTeX Compiler] PDF saved successfully. File size: %d bytes", final_pdf_path.stat().st_size)
                
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


# =============================================================================
# Helper Functions for Error Handling
# =============================================================================

def _parse_latex_errors(log: str) -> dict:
    """
    Parse LaTeX compilation log to extract error information.
    
    Returns:
        Dictionary with error details
    """
    if not log:
        return {"error_type": "UNKNOWN", "message": "No log available"}
    
    errors = []
    lines = log.split('\n')
    
    for i, line in enumerate(lines):
        if line.startswith('!'):
            # LaTeX error line
            error_msg = line[1:].strip()
            
            # Try to extract line number from next lines
            line_number = None
            char_offset = None
            context_lines = []
            
            # Look ahead for line number
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j]
                # Look for line number pattern: "l.123" or "l.123 " 
                line_match = re.search(r'l\.(\d+)', next_line)
                if line_match:
                    line_number = int(line_match.group(1))
                    context_lines.append(next_line)
                    break
                if next_line.strip() and not next_line.startswith('!'):
                    context_lines.append(next_line)
            
            errors.append({
                "error_type": "COMPILE_ERROR",
                "message": error_msg,
                "line_number": line_number,
                "char_offset": char_offset,
                "context": '\n'.join(context_lines[:5]) if context_lines else None
            })
    
    # Common error patterns
    if "Too many }'s" in log:
        errors.append({
            "error_type": "BRACKET_MISMATCH",
            "message": "Too many closing braces",
            "line_number": None,
            "char_offset": None,
            "context": None
        })
    
    if "missing \\item" in log.lower() or "Something's wrong--perhaps a missing \\item" in log:
        errors.append({
            "error_type": "LIST_STRUCTURE_ERROR",
            "message": "Missing \\item in list environment",
            "line_number": None,
            "char_offset": None,
            "context": None
        })
    
    if "Undefined control sequence" in log:
        # Try to extract the undefined command
        undefined_match = re.search(r'Undefined control sequence.*?\\\\([a-zA-Z@]+)', log)
        if undefined_match:
            cmd = undefined_match.group(1)
            errors.append({
                "error_type": "UNDEFINED_COMMAND",
                "message": f"Undefined control sequence: \\{cmd}",
                "line_number": None,
                "char_offset": None,
                "context": None
            })
    
    if "Missing \\begin{document}" in log:
        errors.append({
            "error_type": "MISSING_DOCUMENT_STRUCTURE",
            "message": "Missing \\begin{document}",
            "line_number": None,
            "char_offset": None,
            "context": None
        })
    
    return {
        "errors": errors if errors else [{"error_type": "UNKNOWN", "message": "Compilation failed"}],
        "error_count": len(errors) if errors else 1
    }


@app.post("/compile")
async def compile_latex(request: CompileRequest):
    """
    Compile LaTeX source to PDF.
    
    Returns the compiled PDF file or an error with the compilation log.
    """
    compilation_id = request.filename or str(uuid.uuid4())
    logger.info("[LaTeX Service] Compiling LaTeX: %s", compilation_id)
    logger.info("[LaTeX Service] LaTeX source length: %d chars", len(request.latex_source))
    logger.debug("[LaTeX Service] LaTeX source preview (first 200 chars): %s", request.latex_source[:200])
    
    # Get template directory if specified
    template_dir = None
    compile_runs = 2
    if request.template_id:
        logger.info("[LaTeX Service] Template ID specified: %s", request.template_id)
        template = template_manager.get_template(request.template_id)
        if template:
            template_dir = template_manager.get_template_dir(request.template_id)
            compile_runs = template.compile_runs
            logger.info("[LaTeX Service] Using template directory: %s, compile_runs: %d", template_dir, compile_runs)
    
    # Validate LaTeX security
    logger.info("[LaTeX Service] Validating LaTeX source for security (checking for forbidden commands)")
    if not template_manager._validate_latex_security(request.latex_source):
        logger.error("[LaTeX Service] LaTeX security validation failed: forbidden commands detected")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "LATEX_VALIDATION_FAILED",
                "compilation_id": compilation_id,
                "error": "LaTeX source contains forbidden commands",
                "details": {"error_type": "FORBIDDEN_COMMAND"},
                "sample": request.latex_source[:1000] if len(request.latex_source) > 1000 else request.latex_source
            }
        )
    
    # Validate LaTeX source structure
    logger.info("[LaTeX Service] Validating LaTeX source structure (brackets, environments, commands, etc.)")
    validation_result = latex_validator.validate(request.latex_source)
    
    # Log validation metrics
    if not validation_result.is_valid:
        logger.warning(
            "[LaTeX Service] LaTeX validation failed for compilation %s: %d errors",
            compilation_id,
            len(validation_result.errors)
        )
        # Log error categories
        error_categories = {}
        for error in validation_result.errors:
            error_type = error.error_type.value
            error_categories[error_type] = error_categories.get(error_type, 0) + 1
        logger.warning("[LaTeX Service] Validation error categories: %s", error_categories)
    else:
        logger.info("[LaTeX Service] LaTeX validation passed")
    
    if not validation_result.is_valid:
        # Format validation errors
        error_details = []
        for error in validation_result.errors:
            error_details.append({
                "error_type": error.error_type.value,
                "message": error.message,
                "line_number": error.line_number,
                "char_offset": error.char_offset,
                "context": error.context
            })
        
        raise HTTPException(
            status_code=400,
            detail={
                "code": "LATEX_VALIDATION_FAILED",
                "compilation_id": compilation_id,
                "error": "LaTeX validation failed",
                "details": {
                    "errors": error_details,
                    "error_count": len(error_details)
                },
                "sample": request.latex_source[:1000] if len(request.latex_source) > 1000 else request.latex_source,
                "message": "PDF generation failed due to template/content formatting. Contact support with ID " + compilation_id
            }
        )
    
    # Compile (fix_latex_before_compile is called inside compile method)
    logger.info("[LaTeX Service] Starting LaTeX compilation process (compile_runs: %d)", compile_runs)
    logger.info("[LaTeX Service] Output directory: %s, Filename: %s", OUTPUT_DIR, compilation_id)
    success, log, pdf_path = LaTeXCompiler.compile(
        latex_source=request.latex_source,
        output_dir=OUTPUT_DIR,
        filename=compilation_id,
        template_dir=template_dir,
        compile_runs=compile_runs
    )
    
    # Log compilation metrics
    if success:
        logger.info("[LaTeX Service] LaTeX compilation successful: %s", compilation_id)
        logger.info("[LaTeX Service] PDF saved at: %s", pdf_path)
        if pdf_path and pdf_path.exists():
            logger.info("[LaTeX Service] PDF file size: %d bytes", pdf_path.stat().st_size)
    else:
        logger.error("[LaTeX Service] LaTeX compilation failed: %s", compilation_id)
        logger.error("[LaTeX Service] Compilation log length: %d chars", len(log) if log else 0)
    
    if not success:
        # Parse LaTeX compilation errors
        error_details = _parse_latex_errors(log)
        
        raise HTTPException(
            status_code=400,
            detail={
                "code": "LATEX_COMPILE_ERROR",
                "compilation_id": compilation_id,
                "error": "LaTeX compilation failed",
                "details": error_details,
                "sample": request.latex_source[:1000] if len(request.latex_source) > 1000 else request.latex_source,
                "log": log[-5000:] if log else "",
                "message": "PDF generation failed due to template/content formatting. Contact support with ID " + compilation_id
            }
        )
    
    return FileResponse(
        path=str(pdf_path),
        media_type='application/pdf',
        filename=f"{compilation_id}.pdf"
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
    compilation_id = str(uuid.uuid4())
    
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
    
    # Validate LaTeX source structure
    validation_result = latex_validator.validate(latex_source)
    
    # Log validation metrics
    if not validation_result.is_valid:
        logger.warning(
            "LaTeX validation failed for compilation %s: %d errors",
            compilation_id,
            len(validation_result.errors)
        )
        # Log error categories
        error_categories = {}
        for error in validation_result.errors:
            error_type = error.error_type.value
            error_categories[error_type] = error_categories.get(error_type, 0) + 1
        logger.info("Validation error categories: %s", error_categories)
    
    if not validation_result.is_valid:
        # Format validation errors
        error_details = []
        for error in validation_result.errors:
            error_details.append({
                "error_type": error.error_type.value,
                "message": error.message,
                "line_number": error.line_number,
                "char_offset": error.char_offset,
                "context": error.context
            })
        
        raise HTTPException(
            status_code=400,
            detail={
                "code": "LATEX_VALIDATION_FAILED",
                "compilation_id": compilation_id,
                "error": "LaTeX validation failed",
                "details": {
                    "errors": error_details,
                    "error_count": len(error_details)
                },
                "sample": latex_source[:1000] if len(latex_source) > 1000 else latex_source,
                "message": "PDF generation failed due to template/content formatting. Contact support with ID " + compilation_id
            }
        )
    
    # Compile
    success, log, pdf_path = LaTeXCompiler.compile(
        latex_source=latex_source,
        output_dir=OUTPUT_DIR,
        filename=compilation_id,
        template_dir=template_dir,
        compile_runs=template.compile_runs
    )
    
    # Log compilation metrics
    if success:
        logger.info("LaTeX compilation successful: %s", compilation_id)
    else:
        logger.error("LaTeX compilation failed: %s", compilation_id)
    
    if not success:
        # Parse LaTeX compilation errors
        error_details = _parse_latex_errors(log)
        
        raise HTTPException(
            status_code=400,
            detail={
                "code": "LATEX_COMPILE_ERROR",
                "compilation_id": compilation_id,
                "error": "LaTeX compilation failed",
                "details": error_details,
                "sample": latex_source[:1000] if len(latex_source) > 1000 else latex_source,
                "log": log[-5000:] if log else "",
                "message": "PDF generation failed due to template/content formatting. Contact support with ID " + compilation_id
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
