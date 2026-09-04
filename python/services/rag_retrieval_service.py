from __future__ import annotations

import logging
from typing import Any

from config.settings import AppSettings
from repositories.chroma import search_by_embedding
from repositories.db import _fetch_query_embedding
from repositories.es_client import search_unified

logger = logging.getLogger(__name__)


class RagRetrievalService:
    """Unified RAG retrieval service for both review pipelines."""

    def __init__(self, settings: AppSettings | None = None):
        self.settings = settings or AppSettings()
        self._reranker: Any | None = None  # Lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        nl_query: str,
        code_metadata: list[dict] | None = None,
        top_k: int = 5,
    ) -> tuple[list[dict], str, str | None]:
        """Unified retrieval: NL query + code metadata.

        Args:
            nl_query: Natural language search query
            code_metadata: List of code entity dicts with 'name', 'language',
                          'signature', 'kind' keys (optional)
            top_k: Number of results to return

        Returns:
            (results, status, reason)
            status: "NORMAL" | "DEGRADED" | "NO_RELEVANT_INCIDENTS"
        """
        # 1. Optional query rewrite (default off)
        queries = self._maybe_rewrite_query(nl_query)

        # 2. Build enhanced query
        enhanced_query = self._build_enhanced_query(queries[0], code_metadata)
        query_embedding = _fetch_query_embedding(enhanced_query, self.settings)

        # 3. Vector recall (ChromaDB, no language filter)
        try:
            vector_results = search_by_embedding(
                query_embedding, top_k * 3, self.settings
            )
        except Exception as e:
            logger.warning("Vector recall failed: %s", e)
            vector_results = []

        # 4. Keyword recall (ES BM25 + language boost)
        try:
            keyword_results = search_unified(
                enhanced_query, top_k * 3, code_metadata, self.settings
            )
        except Exception as e:
            logger.warning("Keyword recall failed: %s", e)
            keyword_results = []

        # 5. RRF fusion
        fused = self._rrf_fusion(vector_results, keyword_results, k=self.settings.rrf_k)

        if not fused:
            return [], "NO_RELEVANT_INCIDENTS", "No results from either recall path"

        # 6. Language boost (non-hard-filter)
        if code_metadata:
            fused = self._apply_language_boost(fused, code_metadata)

        # 7. Cross-Encoder rerank (top_k*3 → top_k)
        fused = self._rerank(fused, queries[0], top_k)

        # 8. Score threshold fallback
        if not fused or all(
            item.get("score", 0) < self.settings.min_retrieval_score for item in fused
        ):
            return [], "NO_RELEVANT_INCIDENTS", "All candidates below threshold"

        return fused[:top_k], "NORMAL", None

    # ------------------------------------------------------------------
    # Query rewrite (optional, default off)
    # ------------------------------------------------------------------

    def _maybe_rewrite_query(self, nl_query: str) -> list[str]:
        """Optional LLM query rewrite. Default off to avoid latency."""
        if not self.settings.enable_query_rewrite:
            return [nl_query]

        try:
            from llm.client import LLMClient

            llm = LLMClient(self.settings)
            prompt = f"将以下问题改写为3个不同角度的检索查询（用于事故知识库搜索），每行一个：\n{nl_query}"
            response = llm.chat(prompt, max_tokens=200)
            variants = [line.strip() for line in response.split("\n") if line.strip()][
                :3
            ]
            return [nl_query] + variants
        except Exception as e:
            logger.debug("Query rewrite failed, using original: %s", e)
            return [nl_query]

    # ------------------------------------------------------------------
    # Enhanced query construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_enhanced_query(nl_query: str, code_metadata: list[dict] | None) -> str:
        """Append code entity names/signatures to NL query."""
        if not code_metadata:
            return nl_query

        entity_terms: list[str] = []
        for entity in code_metadata[:5]:  # Limit to 5 entities
            if entity.get("name"):
                entity_terms.append(entity["name"])
            if entity.get("signature"):
                entity_terms.append(entity["signature"])

        if not entity_terms:
            return nl_query

        return f"{nl_query} {' '.join(entity_terms)}"

    # ------------------------------------------------------------------
    # RRF fusion (two-path: vector + keyword)
    # ------------------------------------------------------------------

    @staticmethod
    def _rrf_fusion(
        vector_results: list[dict],
        keyword_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion for two recall paths."""
        scores: dict[str, float] = {}
        id_map: dict[str, dict] = {}

        for rank, item in enumerate(vector_results, start=1):
            key = f"{item.get('title', '')}:{item.get('source', '')}"
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
            id_map[key] = item

        for rank, item in enumerate(keyword_results, start=1):
            key = f"{item.get('title', '')}:{item.get('source', '')}"
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
            id_map.setdefault(key, item)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [id_map[key] for key, _ in ranked]

    # ------------------------------------------------------------------
    # Language boost
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_language_boost(
        results: list[dict], code_metadata: list[dict]
    ) -> list[dict]:
        """Boost same-language results by 20% (non-hard filter)."""
        target_langs = {e.get("language") for e in code_metadata if e.get("language")}
        if not target_langs:
            return results

        for item in results:
            if (
                item.get("language") in target_langs
                or item.get("programming_language") in target_langs
            ):
                item["score"] = item.get("score", 0) * 1.2

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results

    # ------------------------------------------------------------------
    # Cross-Encoder rerank
    # ------------------------------------------------------------------

    def _rerank(self, results: list[dict], query: str, top_k: int) -> list[dict]:
        """Cross-Encoder reranking on top_k*3 candidates."""
        candidates = results[: top_k * 3]

        if not self.settings.enable_rerank or not candidates:
            return candidates[:top_k]

        try:
            reranker = self._get_reranker()
            pairs = [
                (
                    query,
                    item.get("nl_description", "") + " " + item.get("code_content", ""),
                )
                for item in candidates
            ]
            scores = reranker.predict(pairs)

            for item, score in zip(candidates, scores, strict=False):
                item["score"] = float(score)

            candidates.sort(key=lambda x: x["score"], reverse=True)
            return candidates[:top_k]
        except Exception as e:
            logger.warning("Reranking failed, using RRF order: %s", e)
            return candidates[:top_k]

    def _get_reranker(self):
        """Lazy-load Cross-Encoder model."""
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(self.settings.rerank_model_name)
        return self._reranker
