"""
Filesystem-backed LaTeX template store.

Loads resume templates from app/latex/templates/ (metadata.json + .tex files).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

FORBIDDEN_COMMANDS = [
    r'\\write18',
    r'\\immediate\\write18',
    r'\\input\{[|]',
    r'\\openin',
    r'\\openout',
    r'\\read',
    r'\\write(?!18)',
    r'\\catcode',
    r'\\special\{.*shell',
]


@dataclass
class TemplateMetadata:
    id: str
    name: str
    description: str
    author: str
    version: str
    placeholders: list[str] = field(default_factory=list)
    default_filename: str = "resume"


def _templates_dir() -> Path:
    return Path(getattr(settings, 'LATEX_TEMPLATES_DIR', Path(__file__).resolve().parent / 'templates'))


def _validate_latex_security(latex_source: str) -> bool:
    for pattern in FORBIDDEN_COMMANDS:
        if re.search(pattern, latex_source, re.IGNORECASE):
            return False
    return True


def _load_template_metadata(template_dir: Path) -> Optional[TemplateMetadata]:
    metadata_path = template_dir / "metadata.json"
    template_path = template_dir / "template.tex"

    if not metadata_path.exists() or not template_path.exists():
        logger.warning("Template %s missing metadata.json or template.tex", template_dir.name)
        return None

    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata_dict = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Invalid metadata in %s: %s", metadata_path, exc)
        return None

    required = ('id', 'name', 'description', 'author', 'version')
    if not all(key in metadata_dict for key in required):
        logger.error("Metadata missing required fields in %s", metadata_path)
        return None

    if metadata_dict['id'] != template_dir.name:
        logger.warning(
            "Template ID mismatch: metadata says '%s' but directory is '%s'",
            metadata_dict['id'],
            template_dir.name,
        )
        return None

    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()

    if not _validate_latex_security(template_content):
        logger.error("Template %s contains forbidden commands", metadata_dict['id'])
        return None

    return TemplateMetadata(
        id=metadata_dict['id'],
        name=metadata_dict['name'],
        description=metadata_dict['description'],
        author=metadata_dict['author'],
        version=metadata_dict['version'],
        placeholders=metadata_dict.get('placeholders', []),
        default_filename=metadata_dict.get('default_filename', 'resume'),
    )


def _load_templates_cache() -> dict[str, TemplateMetadata]:
    templates_dir = _templates_dir()
    cache: dict[str, TemplateMetadata] = {}

    if not templates_dir.exists():
        logger.warning("Templates directory does not exist: %s", templates_dir)
        return cache

    for template_dir in templates_dir.iterdir():
        if not template_dir.is_dir():
            continue
        metadata = _load_template_metadata(template_dir)
        if metadata:
            cache[metadata.id] = metadata
            logger.debug("Loaded template: %s (v%s)", metadata.id, metadata.version)

    return cache


def list_templates() -> list[TemplateMetadata]:
    return list(_load_templates_cache().values())


def get_template(template_id: str) -> Optional[TemplateMetadata]:
    return _load_templates_cache().get(template_id)


def get_template_dir(template_id: str) -> Optional[Path]:
    if template_id not in _load_templates_cache():
        return None
    return _templates_dir() / template_id


def get_template_content(template_id: str) -> Optional[str]:
    template_dir = get_template_dir(template_id)
    if not template_dir:
        return None

    template_path = template_dir / "template.tex"
    if not template_path.exists():
        return None

    return template_path.read_text(encoding='utf-8')


def get_resume_template_content(template_id: str) -> Optional[str]:
    template_dir = get_template_dir(template_id)
    if not template_dir:
        return None

    resume_template_path = template_dir / "resume_template.tex"
    if not resume_template_path.exists():
        return None

    return resume_template_path.read_text(encoding='utf-8')


def get_main_template_content() -> Optional[str]:
    main_path = _templates_dir() / "main.tex"
    if not main_path.exists():
        return None
    return main_path.read_text(encoding='utf-8')


def has_preview_files(template_id: str) -> bool:
    template_dir = get_template_dir(template_id)
    if not template_dir:
        return False
    return (template_dir / "preview.pdf").exists() and (template_dir / "preview.png").exists()


def get_preview_info(template_id: str) -> dict:
    template_dir = get_template_dir(template_id)
    if not template_dir:
        return {"has_preview": False}

    pdf_path = template_dir / "preview.pdf"
    if not pdf_path.exists():
        return {"has_preview": False}

    stat = pdf_path.stat()
    return {
        "has_preview": True,
        "preview_generated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }
