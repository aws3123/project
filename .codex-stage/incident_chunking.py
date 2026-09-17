"""Create retrieval-sized, evidence-preserving chunks for incident documents.

Document ingestion uses this module for every source format. A chunk keeps its
section and page provenance so a RAG result can point back to the paragraph and
the figures that explain it.
"""

from __future__ import annotations

import re
from typing import Any

from services.document_loader import LoadedDocument


_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_NUMBERED_HEADING = re.compile(
    r"^(?:第[一二三四五六七八九十百0-9]+[章节]|\d+(?:\.\d+){0,4}[、.])\s*(.+?)\s*$",
    re.MULTILINE,
)


def _title_for_offset(text: str, offset: int, fallback: str) -> str:
    """Return the nearest preceding Markdown or numbered heading."""
    candidates: list[tuple[int, str]] = []
    for pattern in (_MARKDOWN_HEADING, _NUMBERED_HEADING):
        for match in pattern.finditer(text):
            if match.start() <= offset:
                candidates.append((match.start(), match.group(1).strip()))
    if not candidates:
        return fallback
    return max(candidates, key=lambda item: item[0])[1] or fallback


def _split_text(text: str, max_chars: int, overlap: int) -> list[tuple[int, str]]:
    """Split at paragraph boundaries where possible and retain small overlap."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [(0, text)]

    pieces: list[tuple[int, str]] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            boundary = max(
                text.rfind("\n\n", start + max_chars // 2, end),
                text.rfind("\n", start + max_chars // 2, end),
                text.rfind("。", start + max_chars // 2, end),
                text.rfind(". ", start + max_chars // 2, end),
            )
            if boundary > start:
                end = boundary + (2 if text.startswith("\n\n", boundary) else 1)
        chunk = text[start:end].strip()
        if chunk:
            pieces.append((start, chunk))
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return pieces


def build_document_region_chunks(
    document: LoadedDocument,
    *,
    max_chars: int = 1800,
    overlap: int = 180,
) -> list[dict[str, Any]]:
    """Create text-first chunks by PDF page or document section.

    Figure summaries are attached later, after OCR/VL completes. The returned
    metadata deliberately retains page ranges, so that attachment is deterministic.
    """
    pages = document.pages or [document.text]
    chunks: list[dict[str, Any]] = []
    sequence = 0

    for page_index, page_text in enumerate(pages):
        fallback_title = f"第 {page_index + 1} 页" if document.pages else document.source_file
        for offset, text in _split_text(page_text, max_chars, overlap):
            sequence += 1
            section_title = _title_for_offset(page_text, offset, fallback_title)
            page_start = page_index + 1 if document.pages else None
            chunks.append(
                {
                    "id": f"{document.source_file}:section:{sequence}",
                    "nl_description": text,
                    "code_content": "",
                    "embedding": None,
                    "ast_metadata": {
                        "entity_name": "",
                        "entity_kind": "document_section",
                        "fully_qualified_name": "",
                        "language": "text",
                        "signature": "",
                        "parent_class": None,
                        "line_start": 0,
                        "line_end": 0,
                        "ast_status": "not_applicable",
                    },
                    "doc_metadata": {
                        "source_doc": document.source_file,
                        "section_title": section_title,
                        "position_in_doc": sequence,
                        "page_start": page_start,
                        "page_end": page_start,
                        "chunk_type": "section",
                        "risk_type": "general",
                        "image_urls": [],
                        "image_texts": [],
                        "image_relations": [],
                        "image_bboxes": [],
                    },
                }
            )
    return chunks


def attach_figure_evidence(
    region_chunks: list[dict[str, Any]], figure_chunks: list[dict[str, Any]]
) -> None:
    """Attach OCR/VL figure evidence to the text region on the same PDF page."""
    for figure in figure_chunks:
        metadata = figure.get("doc_metadata", {})
        page_index = metadata.get("page_index")
        if page_index is None:
            continue
        page_number = int(page_index) + 1
        targets = [
            chunk
            for chunk in region_chunks
            if chunk.get("doc_metadata", {}).get("page_start")
            <= page_number
            <= chunk.get("doc_metadata", {}).get("page_end")
        ]
        if not targets:
            continue
        target = targets[0]
        summary = figure.get("nl_description", "").strip()
        if summary:
            target["nl_description"] += f"\n\n[图像说明]\n{summary}"
        target_meta = target["doc_metadata"]
        for field in ("image_urls", "image_texts", "image_relations", "image_bboxes"):
            target_meta.setdefault(field, []).extend(metadata.get(field, []))
