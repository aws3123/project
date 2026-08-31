from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CodeBlock:
    """A code block extracted from document text."""

    content: str           # Original code text (including comments)
    language: str          # java / python / typescript / sql / unknown
    position_in_doc: int   # Position index in document (1-based)
    preceding_nl: str      # Associated NL description (preceding paragraph)
    section_title: str     # Section heading the block belongs to
    ast_status: str        # pending / parsed / fallback / boundary_unclear


@dataclass
class ExtractedSection:
    """A section of the document — either NL or code."""

    type: str  # "nl" or "code"
    content: str
    associated_code: str | None = None
    code_language: str | None = None
    section_title: str = ""
    position_in_doc: int = 0


# ---------------------------------------------------------------------------
# Language detection patterns
# ---------------------------------------------------------------------------

_LANG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("java", re.compile(r"\b(public\s+class|private\s+void|@Override|import\s+java\.)", re.I)),
    ("python", re.compile(r"\b(def\s+\w+|import\s+\w+|from\s+\w+\s+import|if\s+__name__)", re.I)),
    ("typescript", re.compile(r"\b(interface\s+\w+|export\s+(class|function|const)|=>\s)", re.I)),
    ("sql", re.compile(r"\b(SELECT\s+|CREATE\s+TABLE|INSERT\s+INTO|UPDATE\s+\w+\s+SET)", re.I)),
]

_CODE_KEYWORDS = re.compile(
    r"\b(public|private|protected|class|void|return|if|else|for|while|"
    r"def|import|from|function|var|let|const|interface|export|"
    r"SELECT|INSERT|UPDATE|DELETE|CREATE|TABLE)\b",
    re.I,
)

_CHINESE_PUNCT = re.compile(r"[，。？！；：、""''（）【】《》]")


def _detect_language(code: str) -> str:
    """Detect programming language from code content."""
    # Check Markdown fence language hint first (handled by caller)
    for lang, pattern in _LANG_PATTERNS:
        if pattern.search(code):
            return lang
    return "unknown"


# Heuristic scoring thresholds for code paragraph detection
_SEMICOLON_RATE_THRESHOLD = 0.02   # ~1 semicolon per 50 chars
_BRACE_RATE_THRESHOLD = 0.02
_KEYWORD_SCORE_HIGH = 2            # 2+ keyword hits
_KEYWORD_SCORE_LOW = 1             # 1 keyword hit
_KEYWORD_SCORE_PARTIAL = 0.5
_INDENTED_LINE_RATIO = 0.5         # >50% lines indented
_CHINESE_PUNCT_PENALTY = -2
_CODE_SCORE_THRESHOLD = 3          # score >= this means "definitely code"
_BOUNDARY_UNCLEAR_MAX_SCORE = 3    # 0 < score < this means "boundary unclear"


def _is_code_paragraph(text: str) -> tuple[bool, float]:
    """Heuristic scoring: is this paragraph code?

    Returns (is_code, score).
    """
    lines = text.strip().split("\n")
    if not lines or not text.strip():
        return False, 0.0

    score = 0.0
    total_chars = max(len(text), 1)

    # Semicolons, braces frequency
    semicolons = text.count(";")
    braces = text.count("{") + text.count("}")
    parens = text.count("(") + text.count(")")
    semicolon_rate = semicolons / total_chars
    brace_rate = braces / total_chars

    if semicolon_rate > _SEMICOLON_RATE_THRESHOLD:
        score += 2
    if brace_rate > _BRACE_RATE_THRESHOLD:
        score += 2

    # Code keywords
    keyword_hits = len(_CODE_KEYWORDS.findall(text))
    if keyword_hits >= _KEYWORD_SCORE_HIGH:
        score += 1
    elif keyword_hits >= _KEYWORD_SCORE_LOW:
        score += _KEYWORD_SCORE_PARTIAL

    # Indentation (leading spaces >= 4 on most lines)
    indented_lines = sum(1 for line in lines if line.startswith("    ") or line.startswith("\t"))
    if len(lines) > 1 and indented_lines / len(lines) > _INDENTED_LINE_RATIO:
        score += 1

    # Chinese punctuation penalty
    chinese_hits = len(_CHINESE_PUNCT.findall(text))
    if chinese_hits > 0:
        score += _CHINESE_PUNCT_PENALTY

    return score >= _CODE_SCORE_THRESHOLD, score


# ---------------------------------------------------------------------------
# Markdown fence extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_HTML_CODE_RE = re.compile(r"<pre><code(?:\s+class=\"(\w+)\")?>(.*?)</code></pre>", re.DOTALL | re.IGNORECASE)

_SECTION_HEADER_RE = re.compile(r"^(#{1,6}\s+.+)$", re.MULTILINE)


def _extract_markdown_fences(text: str) -> list[tuple[int, int, str, str]]:
    """Extract Markdown ``` code blocks.

    Returns list of (start, end, language_hint, code_content).
    """
    results = []
    for match in _FENCE_RE.finditer(text):
        lang_hint = match.group(1).lower() or ""
        code = match.group(2).strip()
        results.append((match.start(), match.end(), lang_hint, code))
    return results


def _extract_html_code_tags(text: str) -> list[tuple[int, int, str, str]]:
    """Extract <pre><code> blocks from HTML."""
    results = []
    for match in _HTML_CODE_RE.finditer(text):
        lang_hint = match.group(1).lower() or ""
        code = match.group(2).strip()
        # Basic HTML entity decoding
        code = code.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
        results.append((match.start(), match.end(), lang_hint, code))
    return results


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def _extract_with_structured_blocks(
    text: str,
    structured_blocks: list[tuple[int, int, str, str]],
) -> tuple[list[ExtractedSection], list[CodeBlock]]:
    """Extract sections using known structured code block positions (Layer 1)."""
    sections: list[ExtractedSection] = []
    code_blocks: list[CodeBlock] = []
    position = 0
    last_nl = ""
    code_position = 0
    current_section = ""
    cursor = 0

    for block_start, block_end, lang_hint, code_content in structured_blocks:
        # Text before this code block is NL
        if block_start > cursor:
            nl_text = text[cursor:block_start].strip()
            if nl_text:
                header_match = _SECTION_HEADER_RE.search(nl_text)
                if header_match:
                    current_section = header_match.group(1).strip()

                nl_paras = [p.strip() for p in nl_text.split("\n\n") if p.strip()]
                for para in nl_paras:
                    position += 1
                    sections.append(ExtractedSection(
                        type="nl", content=para,
                        section_title=current_section, position_in_doc=position,
                    ))
                    last_nl = para

        # Add the code block
        code_position += 1
        language = lang_hint or _detect_language(code_content)
        cb = CodeBlock(
            content=code_content, language=language,
            position_in_doc=code_position, preceding_nl=last_nl,
            section_title=current_section, ast_status="pending",
        )
        code_blocks.append(cb)

        position += 1
        sections.append(ExtractedSection(
            type="code", content=code_content,
            associated_code=code_content, code_language=language,
            section_title=current_section, position_in_doc=position,
        ))
        cursor = block_end

    # Remaining text after last code block
    if cursor < len(text):
        remaining = text[cursor:].strip()
        if remaining:
            nl_paras = [p.strip() for p in remaining.split("\n\n") if p.strip()]
            for para in nl_paras:
                position += 1
                sections.append(ExtractedSection(
                    type="nl", content=para,
                    section_title=current_section, position_in_doc=position,
                ))
                last_nl = para

    return sections, code_blocks


def _extract_with_heuristic(
    paragraphs: list[str],
) -> tuple[list[ExtractedSection], list[CodeBlock]]:
    """Extract sections using paragraph-level heuristic scoring (Layer 2/3)."""
    sections: list[ExtractedSection] = []
    code_blocks: list[CodeBlock] = []
    position = 0
    last_nl = ""
    code_position = 0
    current_section = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Check for section header
        header_match = _SECTION_HEADER_RE.match(para)
        if header_match:
            current_section = para
            position += 1
            sections.append(ExtractedSection(
                type="nl", content=para,
                section_title=current_section, position_in_doc=position,
            ))
            last_nl = para
            continue

        is_code, score = _is_code_paragraph(para)

        if is_code:
            code_position += 1
            language = _detect_language(para)
            cb = CodeBlock(
                content=para, language=language,
                position_in_doc=code_position, preceding_nl=last_nl,
                section_title=current_section, ast_status="pending",
            )
            code_blocks.append(cb)
            position += 1
            sections.append(ExtractedSection(
                type="code", content=para,
                associated_code=para, code_language=language,
                section_title=current_section, position_in_doc=position,
            ))
        elif 0 < score < _BOUNDARY_UNCLEAR_MAX_SCORE:
            # Boundary unclear — treat as code with fallback status
            code_position += 1
            language = _detect_language(para)
            cb = CodeBlock(
                content=para, language=language,
                position_in_doc=code_position, preceding_nl=last_nl,
                section_title=current_section, ast_status="boundary_unclear",
            )
            code_blocks.append(cb)
            position += 1
            sections.append(ExtractedSection(
                type="code", content=para,
                associated_code=para, code_language=language,
                section_title=current_section, position_in_doc=position,
            ))
        else:
            position += 1
            sections.append(ExtractedSection(
                type="nl", content=para,
                section_title=current_section, position_in_doc=position,
            ))
            last_nl = para

    return sections, code_blocks


def extract_sections(text: str) -> tuple[list[ExtractedSection], list[CodeBlock]]:
    """Extract NL and code sections from document text.

    Returns:
        (sections, code_blocks)
        - sections: ordered list of NL and code sections
        - code_blocks: ordered list of extracted code blocks with metadata
    """
    # Find all structured code blocks (Markdown fences + HTML tags)
    structured_blocks: list[tuple[int, int, str, str]] = []
    structured_blocks.extend(_extract_markdown_fences(text))
    structured_blocks.extend(_extract_html_code_tags(text))
    structured_blocks.sort(key=lambda x: x[0])

    if structured_blocks:
        sections, code_blocks = _extract_with_structured_blocks(text, structured_blocks)
    else:
        paragraphs = re.split(r"\n\n+", text)
        sections, code_blocks = _extract_with_heuristic(paragraphs)

    logger.info(
        "Extracted %d sections (%d NL, %d code) from document",
        len(sections),
        sum(1 for s in sections if s.type == "nl"),
        len(code_blocks),
    )
    return sections, code_blocks
