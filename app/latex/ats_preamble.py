"""
ATS resume template preamble enforcement for LaTeX compile pipeline.

Ensures custom resume macros are defined and forbidden/undefined commands like
\\textbar are normalized before validation and compilation.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ATS_MACRO_NAMES = (
    "resumeHeader",
    "resumeContactLine",
    "resumeSectionTitle",
    "resumeSummaryText",
    "resumeExperienceHeading",
    "resumeEducationEntry",
    "resumeProjectEntry",
    "resumeSkillLine",
    "resumeItem",
    "resumeDetailLine",
    "resumeEntryHeading",
    "resumeTagList",
)

_MACROS_INPUT_RE = re.compile(r"\\input\{resume_macros\.tex\}")


def _resolve_macros_tex_path() -> Path:
    """Locate resume_macros.tex (single source of truth for layout/spacing)."""
    path = Path(__file__).resolve().parent / "templates" / "main" / "resume_macros.tex"
    if path.is_file():
        return path
    raise FileNotFoundError(f"resume_macros.tex not found at {path}")


@lru_cache(maxsize=1)
def load_ats_macro_block_from_template() -> str:
    """Load macro definitions from resume_macros.tex; convert to \\providecommand for injection."""
    raw = _resolve_macros_tex_path().read_text(encoding="utf-8").strip()
    return re.sub(r"\\newcommand", r"\\providecommand", raw)


def get_ats_macro_block() -> str:
    """Return the canonical ATS macro block loaded from the LaTeX template file."""
    return load_ats_macro_block_from_template()

_MACRO_DEF_START = re.compile(
    rf"\\(?:new|renew|provide)command\*?(?:\[[^\]]*\])?\{{\\({'|'.join(ATS_MACRO_NAMES)})\}}",
)


def _mask_latex_comments(source: str) -> str:
    chars = list(source)
    i = 0
    while i < len(chars):
        if chars[i] == "%" and (i == 0 or chars[i - 1] != "\\"):
            while i < len(chars) and chars[i] != "\n":
                chars[i] = " "
                i += 1
        else:
            i += 1
    return "".join(chars)


def _find_marker_positions(source: str, marker: str) -> list[int]:
    masked = _mask_latex_comments(source)
    return [match.start() for match in re.finditer(re.escape(marker), masked)]


def _remove_ats_macro_definitions(source: str) -> tuple[str, int]:
    """Remove AI-defined ATS macro blocks so canonical definitions can be injected."""
    removed = 0
    while True:
        match = _MACRO_DEF_START.search(source)
        if not match:
            break
        start = match.start()
        brace_idx = source.find("{", match.end() - 1)
        if brace_idx == -1:
            break
        depth = 0
        end_idx = None
        for idx in range(brace_idx, len(source)):
            char = source[idx]
            if char == "{" and (idx == 0 or source[idx - 1] != "\\"):
                depth += 1
            elif char == "}" and (idx == 0 or source[idx - 1] != "\\"):
                depth -= 1
                if depth == 0:
                    end_idx = idx
                    break
        if end_idx is None:
            break
        source = source[:start] + source[end_idx + 1 :]
        removed += 1
    return source, removed


def expand_resume_items(source: str) -> str:
    """Expand \\resumeItem{...} to \\item ... so lists compile reliably."""
    return re.sub(r"\\resumeItem\{([^}]*)\}", r"\\item \1", source)


def repair_malformed_documentclass(source: str) -> str:
    """Fix AI-duplicated documentclass suffix like {article]{article}."""
    repaired, count = re.subn(
        r"(\\documentclass(?:\[[^\]]*\])?\{[^}\]]+)\]\{[^}]+\}",
        r"\1}",
        source,
        count=1,
    )
    return repaired


def escape_unescaped_ampersands_in_body(source: str) -> str:
    """Escape raw & characters in document body (common in skill/category labels)."""
    marker = "\\begin{document}"
    end_marker = "\\end{document}"
    begin = source.find(marker)
    if begin == -1:
        return source
    body_start = begin + len(marker)
    end = source.find(end_marker, body_start)
    if end == -1:
        return source
    body = source[body_start:end]
    escaped_body = re.sub(r"(?<!\\)&", r"\\&", body)
    return source[:body_start] + escaped_body + source[end:]


def repair_corrupted_ats_macros(source: str) -> str:
    """Fix common AI corruptions of template macro line breaks before compile."""
    replacements = (
        (r"\fi\[2pt]", r"\fi\\[2pt]"),
        (r"\textit{#2}\%", r"\textit{#2}\\%"),
        (r"\textit{#2} \%", r"\textit{#2}\\%"),
    )
    for old, new in replacements:
        if old in source:
            source = source.replace(old, new)
    for pattern, replacement in (
        (r"\\sectiontitle\{([^}]+)\}", r"\\section*{\1}"),
        (r"\\sectionTitle\{([^}]+)\}", r"\\section*{\1}"),
        (r"\\SectionTitle\{([^}]+)\}", r"\\section*{\1}"),
    ):
        source = re.sub(pattern, replacement, source)
    return source


def tighten_section_title_spacing(source: str) -> str:
    """Remove extra blank lines or vspace between a section title and its content."""
    source = re.sub(
        r"(\\resumeSectionTitle\{[^}]+\})\s*\n\s*\n+",
        r"\1\n",
        source,
    )
    source = re.sub(
        r"(\\resumeSectionTitle\{[^}]+\})\s*\n\s*\\vspace\{[^}]+\}\s*\n",
        r"\1\n",
        source,
    )
    source = re.sub(
        r"(\\end\{(?:itemize|enumerate)\})\s*\\vspace\{[^}]+\}(\s*(?:%[^\n]*\n)*)?(?=\\resumeSectionTitle)",
        r"\1\2",
        source,
    )
    return source


def _macro_is_defined(source: str, name: str) -> bool:
    return bool(
        re.search(
            rf"\\(?:new|renew|provide)command\*?(?:\[[^\]]*\])?\{{\\{name}\}}",
            source,
        )
    )


def analyze_ats_preamble(source: str) -> dict[str, Any]:
    used = [name for name in ATS_MACRO_NAMES if f"\\{name}" in source]
    defined = [name for name in ATS_MACRO_NAMES if _macro_is_defined(source, name)]
    return {
        "textbar_count": len(re.findall(r"\\textbar\b", source)),
        "ats_macros_used": used,
        "ats_macros_defined": defined,
        "ats_macros_missing": [name for name in used if name not in defined],
        "has_begin_document": "\\begin{document}" in source,
    }


def ensure_ats_resume_preamble(latex_source: str) -> str:
    """Normalize ATS resume LaTeX before validator/compile."""
    latex_source = repair_malformed_documentclass(latex_source)
    latex_source = re.sub(r"\\textbar\b", r"$|$", latex_source)
    latex_source = repair_corrupted_ats_macros(latex_source)
    latex_source = expand_resume_items(latex_source)
    latex_source = escape_unescaped_ampersands_in_body(latex_source)
    latex_source = tighten_section_title_spacing(latex_source)

    uses_ats = any(f"\\{name}" in latex_source for name in ATS_MACRO_NAMES)
    if not uses_ats:
        return latex_source

    stripped_source, _removed_defs = _remove_ats_macro_definitions(latex_source)
    stripped_source = _MACROS_INPUT_RE.sub("", stripped_source)
    macro_block = get_ats_macro_block()
    begin_doc = stripped_source.find("\\begin{document}")
    if begin_doc != -1:
        latex_source = (
            stripped_source[:begin_doc].rstrip()
            + "\n\n"
            + macro_block
            + "\n\n"
            + stripped_source[begin_doc:]
        )
    else:
        latex_source = stripped_source.rstrip() + "\n\n" + macro_block + "\n"

    return remove_empty_list_environments(latex_source)


def remove_empty_list_environments(source: str) -> str:
    """Remove only directly empty list environments (no nested content between begin/end)."""
    empty_list_pattern = re.compile(
        r"\\begin\{(itemize|enumerate|description)\}(\s*)\\end\{\1\}",
        re.MULTILINE,
    )
    while True:
        source, count = empty_list_pattern.subn("", source)
        if count == 0:
            break
    return source


def normalize_document_envelope(latex_source: str) -> str:
    """Ensure a single well-formed document wrapper before validation/compile."""
    begin_marker = "\\begin{document}"
    end_marker = "\\end{document}"
    begin_positions = _find_marker_positions(latex_source, begin_marker)
    end_positions = _find_marker_positions(latex_source, end_marker)

    if not begin_positions:
        docclass_match = re.search(r"\\documentclass[^\n]*", latex_source)
        if docclass_match:
            insert_pos = docclass_match.end()
            next_newline = latex_source.find("\n", insert_pos)
            insert_at = next_newline + 1 if next_newline != -1 else insert_pos
            latex_source = (
                latex_source[:insert_at]
                + "\n"
                + begin_marker
                + "\n"
                + latex_source[insert_at:]
            )
        else:
            latex_source = begin_marker + "\n" + latex_source
        begin_positions = _find_marker_positions(latex_source, begin_marker)

    if len(begin_positions) > 1:
        for pos in reversed(begin_positions[1:]):
            latex_source = latex_source[:pos] + latex_source[pos + len(begin_marker) :]

    end_positions = _find_marker_positions(latex_source, end_marker)
    if len(end_positions) > 1:
        for pos in reversed(end_positions[:-1]):
            latex_source = latex_source[:pos] + latex_source[pos + len(end_marker) :]

    if not _find_marker_positions(latex_source, end_marker):
        latex_source = latex_source.rstrip() + "\n" + end_marker

    return latex_source
