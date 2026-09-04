from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import AppSettings

logger = logging.getLogger(__name__)


@dataclass
class LoadedDocument:
    """Unified document representation after loading."""

    text: str
    source_file: str
    format: str  # md / html / pdf / docx / txt
    pages: list[str] = field(default_factory=list)  # PDF pages (optional)


def _detect_format(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    return {
        ".md": "md",
        ".markdown": "md",
        ".html": "html",
        ".htm": "html",
        ".pdf": "pdf",
        ".docx": "docx",
    }.get(ext, "txt")


def _load_markdown(file_path: Path) -> str:
    """Load Markdown as plain text (no extra dependency)."""
    return file_path.read_text(encoding="utf-8", errors="replace")


def _load_html(file_path: Path) -> str:
    """Load HTML, strip tags to plain text."""
    try:
        from langchain_community.document_loaders import UnstructuredHTMLLoader

        docs = UnstructuredHTMLLoader(str(file_path)).load()
        return "\n\n".join(d.page_content for d in docs)
    except ImportError:
        logger.warning("unstructured not installed, falling back to raw HTML read")
        return file_path.read_text(encoding="utf-8", errors="replace")


def _load_pdf(file_path: Path) -> list[str]:
    """Load PDF, return list of page texts."""
    try:
        from langchain_community.document_loaders import PyPDFLoader

        loader = PyPDFLoader(str(file_path))
        pages = loader.load()
        return [page.page_content for page in pages]
    except ImportError:
        logger.warning("pypdf not installed, trying raw read")
        try:
            import pypdf

            reader = pypdf.PdfReader(str(file_path))
            return [page.extract_text() or "" for page in reader.pages]
        except Exception as e:
            logger.error("PDF load failed for %s: %s", file_path.name, e)
            return [file_path.read_text(encoding="utf-8", errors="replace")]


def _load_docx(file_path: Path) -> str:
    """Load DOCX as plain text."""
    try:
        import docx2txt

        return docx2txt.process(str(file_path))
    except ImportError:
        try:
            from langchain_community.document_loaders import (
                UnstructuredWordDocumentLoader,
            )

            docs = UnstructuredWordDocumentLoader(str(file_path)).load()
            return "\n\n".join(d.page_content for d in docs)
        except ImportError:
            logger.error("Neither docx2txt nor unstructured available for DOCX")
            return ""


def load_document(
    file_path: str | Path, settings: AppSettings | None = None
) -> LoadedDocument | None:
    """Load a single document from file path.

    Returns None if the file cannot be loaded (error is logged).
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("File not found: %s", path)
        return None

    fmt = _detect_format(path)
    logger.info("Loading %s as %s", path.name, fmt)

    try:
        if fmt == "md":
            text = _load_markdown(path)
            return LoadedDocument(text=text, source_file=path.name, format=fmt)

        elif fmt == "html":
            text = _load_html(path)
            return LoadedDocument(text=text, source_file=path.name, format=fmt)

        elif fmt == "pdf":
            pages = _load_pdf(path)
            if not pages:
                logger.warning("PDF yielded no pages: %s", path.name)
                return None
            text = "\n\n".join(pages)
            return LoadedDocument(
                text=text, source_file=path.name, format=fmt, pages=pages
            )

        elif fmt == "docx":
            text = _load_docx(path)
            if not text:
                logger.warning("DOCX yielded no text: %s", path.name)
                return None
            return LoadedDocument(text=text, source_file=path.name, format=fmt)

        else:
            # Unknown format — read as plain text
            text = path.read_text(encoding="utf-8", errors="replace")
            return LoadedDocument(text=text, source_file=path.name, format="txt")

    except Exception as e:
        logger.error("Failed to load %s: %s", path.name, e)
        return None


def load_documents_from_dir(
    docs_dir: str,
    settings: AppSettings | None = None,
) -> list[LoadedDocument]:
    """Load all supported documents from a directory.

    Skips files that fail to load.
    """
    dir_path = Path(docs_dir)
    if not dir_path.is_dir():
        logger.error("Documents directory not found: %s", docs_dir)
        return []

    supported_exts = {".md", ".markdown", ".html", ".htm", ".pdf", ".docx", ".txt"}
    documents: list[LoadedDocument] = []

    for file_path in sorted(dir_path.iterdir()):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in supported_exts:
            continue

        doc = load_document(file_path, settings)
        if doc is not None:
            documents.append(doc)

    logger.info("Loaded %d documents from %s", len(documents), docs_dir)
    return documents
