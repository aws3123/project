from __future__ import annotations

import json
import logging
from pathlib import Path

from config.settings import AppSettings
from repositories import es_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_keyword_index(rows: list[dict], settings: AppSettings | None = None) -> None:
    """Write incident rows into Elasticsearch and keep a JSONL backup."""
    settings = settings or AppSettings()

    # 1. Index into Elasticsearch
    es_client.index_documents(rows, settings=settings)

    # 2. Keep JSONL backup for traceability
    path = Path(settings.chroma_keyword_index_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = {
                "id": str(row["id"]),
                "title": row["title"],
                "snippet": row["snippet"],
                "source": row["source"],
                "service": row.get("service"),
                "tags": row.get("tags", []),
                "image_urls": row.get("image_urls", []),
                "image_texts": row.get("image_texts", []),
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    logger.info("Keyword index written to ES and JSONL backup at %s", path)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_incidents_keyword_local(
    query: str,
    top_k: int,
    settings: AppSettings | None = None,
) -> list[dict]:
    """Search incidents by keyword using Elasticsearch BM25."""
    settings = settings or AppSettings()

    results = es_client.search_documents(query, top_k=top_k, settings=settings)

    return [
        {
            "title": r.get("title", "unknown"),
            "snippet": r.get("snippet", ""),
            "source": "bm25",  # backward-compatible source label
            "service": r.get("service"),
            "tags": r.get("tags", []),
            "image_urls": r.get("image_urls", []),
            "image_texts": r.get("image_texts", []),
            "score": r.get("score", 0),
        }
        for r in results
    ]
