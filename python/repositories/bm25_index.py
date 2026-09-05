from __future__ import annotations

import logging
from typing import Any

from config.settings import AppSettings
from repositories import es_client

logger = logging.getLogger(__name__)


class BM25Index:
    """Elasticsearch-backed keyword index for incident retrieval.

    The class name is preserved for backward compatibility.  Under the hood
    all operations are delegated to :mod:`repositories.es_client`.
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings()
        self.documents: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Build / index
    # ------------------------------------------------------------------

    def build(self, documents: list[dict]) -> None:
        """Index documents into Elasticsearch.

        Each document must have at least 'id', 'title', 'snippet', 'source'.
        """
        self.documents = documents
        if not documents:
            return
        es_client.index_documents(documents, settings=self.settings)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search the Elasticsearch index and return top_k results."""
        results = es_client.search_documents(query, top_k=top_k, settings=self.settings)
        # Normalise source field for backward compatibility
        for doc in results:
            if doc.get("source") == "elasticsearch":
                doc["source"] = "bm25"
        return results

    # ------------------------------------------------------------------
    # Persistence — no longer needed (ES handles it natively)
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """No-op — Elasticsearch persists data automatically."""
        logger.debug("BM25Index.save() is a no-op with ES backend")

    @staticmethod
    def load(path: str) -> BM25Index | None:
        """Return None — ES does not require manual loading."""
        return None
