from __future__ import annotations

import logging
from typing import Any

from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import NotFoundError

from config.settings import AppSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_es_client: Elasticsearch | None = None


def get_es_client(settings: AppSettings | None = None) -> Elasticsearch:
    """Return a cached Elasticsearch client."""
    global _es_client
    if _es_client is None:
        settings = settings or AppSettings()
        _es_client = Elasticsearch(
            hosts=[settings.elasticsearch_url],
            request_timeout=10,
            max_retries=2,
            retry_on_timeout=True,
        )
    return _es_client


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

# Analyzer to use — detected at runtime
_analyzer_cache: dict[str, str] = {}


def _detect_analyzer(client: Elasticsearch, index_name: str) -> str:
    """Detect the best available analyzer for the index."""
    if index_name in _analyzer_cache:
        return _analyzer_cache[index_name]

    # Try ik_max_word first (requires IK plugin)
    try:
        client.indices.analyze(body={"analyzer": "ik_max_word", "text": "测试"})
        analyzer = "ik_max_word"
    except Exception:
        logger.info("IK analyzer not available, falling back to 'standard'")
        analyzer = "standard"

    _analyzer_cache[index_name] = analyzer
    return analyzer


def ensure_index(settings: AppSettings | None = None) -> None:
    """Create the incident keywords index if it does not exist."""
    settings = settings or AppSettings()
    client = get_es_client(settings)
    index_name = settings.es_index_name

    if client.indices.exists(index=index_name):
        logger.debug("ES index '%s' already exists", index_name)
        return

    analyzer = _detect_analyzer(client, index_name)

    body: dict[str, Any] = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": analyzer,
            },
        },
        "mappings": {
            "properties": {
                # Legacy fields
                "title": {"type": "text", "analyzer": analyzer},
                "snippet": {"type": "text", "analyzer": analyzer},
                "source": {"type": "keyword"},
                "service": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "image_urls": {"type": "keyword", "index": False},
                "image_texts": {"type": "text", "index": False},
                # New unified chunk fields
                "nl_description": {"type": "text", "analyzer": analyzer},
                "code_content": {"type": "text", "analyzer": "standard"},
                "entity_name": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "entity_kind": {"type": "keyword"},
                "fully_qualified_name": {"type": "keyword"},
                "language": {"type": "keyword"},
                "programming_language": {"type": "keyword"},
                "signature": {"type": "text", "analyzer": "standard"},
                "source_doc": {"type": "keyword"},
                "section_title": {"type": "text", "analyzer": analyzer},
                "risk_type": {"type": "keyword"},
                "position_in_doc": {"type": "integer"},
                "ast_status": {"type": "keyword"},
                "has_code": {"type": "boolean"},
            }
        },
    }

    client.indices.create(index=index_name, body=body)
    logger.info("Created ES index '%s' with analyzer '%s'", index_name, analyzer)


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def index_documents(rows: list[dict], settings: AppSettings | None = None) -> None:
    """Bulk-index incident documents into Elasticsearch."""
    if not rows:
        return

    settings = settings or AppSettings()
    ensure_index(settings)
    client = get_es_client(settings)
    index_name = settings.es_index_name

    actions = []
    for row in rows:
        doc_id = str(row.get("id", ""))
        if not doc_id:
            continue

        doc = {
            "title": row.get("title", ""),
            "snippet": row.get("snippet", ""),
            "source": row.get("source", "unknown"),
            "service": row.get("service"),
            "tags": row.get("tags", []),
            "image_urls": row.get("image_urls", []),
            "image_texts": row.get("image_texts", []),
        }
        actions.append(
            {
                "_index": index_name,
                "_id": doc_id,
                "_source": doc,
            }
        )

    if actions:
        success, errors = helpers.bulk(client, actions, raise_on_error=False)
        if errors:
            logger.warning(
                "ES bulk indexing had %d errors: %s", len(errors), errors[:3]
            )
        logger.info("Indexed %d documents into ES '%s'", success, index_name)


def index_unified_chunks(
    chunks: list[dict], settings: AppSettings | None = None
) -> None:
    """Bulk-index unified chunks (NL + code + AST metadata) into ES."""
    if not chunks:
        return

    settings = settings or AppSettings()
    ensure_index(settings)
    client = get_es_client(settings)
    index_name = settings.es_index_name

    actions = []
    for chunk in chunks:
        doc_id = str(chunk.get("id", ""))
        if not doc_id:
            continue

        ast_meta = chunk.get("ast_metadata", {})
        doc_meta = chunk.get("doc_metadata", {})

        doc = {
            # Legacy fields
            "title": doc_meta.get("section_title", ""),
            "snippet": chunk.get("nl_description", ""),
            "source": doc_meta.get("source_doc", "unknown"),
            "tags": doc_meta.get("tags", []),
            "image_urls": doc_meta.get("image_urls", []),
            "image_texts": doc_meta.get("image_texts", []),
            # New unified chunk fields
            "nl_description": chunk.get("nl_description", ""),
            "code_content": chunk.get("code_content", ""),
            "entity_name": ast_meta.get("entity_name", ""),
            "entity_kind": ast_meta.get("entity_kind", "unknown"),
            "fully_qualified_name": ast_meta.get("fully_qualified_name", ""),
            "language": ast_meta.get("language", "unknown"),
            "programming_language": ast_meta.get("language", "unknown"),
            "signature": ast_meta.get("signature", ""),
            "source_doc": doc_meta.get("source_doc", ""),
            "section_title": doc_meta.get("section_title", ""),
            "risk_type": doc_meta.get("risk_type", "general"),
            "position_in_doc": doc_meta.get("position_in_doc", 0),
            "ast_status": ast_meta.get("ast_status", "unknown"),
            "has_code": bool(chunk.get("code_content")),
        }
        actions.append({"_index": index_name, "_id": doc_id, "_source": doc})

    if actions:
        success, errors = helpers.bulk(client, actions, raise_on_error=False)
        if errors:
            logger.warning(
                "ES unified indexing had %d errors: %s", len(errors), errors[:3]
            )
        logger.info("Indexed %d unified chunks into ES '%s'", success, index_name)


# ---------------------------------------------------------------------------
# Search result building
# ---------------------------------------------------------------------------


def _es_hit_to_legacy_result(source: dict, score: float) -> dict:
    """Build a legacy-format result dict from an ES hit _source."""
    return {
        "title": source.get("title", "unknown"),
        "snippet": source.get("snippet", ""),
        "source": source.get("source", "elasticsearch"),
        "service": source.get("service"),
        "tags": source.get("tags", []),
        "image_urls": source.get("image_urls", []),
        "image_texts": source.get("image_texts", []),
        "score": score,
    }


def _es_hit_to_unified_result(source: dict, score: float) -> dict:
    """Build a unified result dict (with code fields) from an ES hit _source."""
    return {
        # Legacy fields
        **_es_hit_to_legacy_result(source, score),
        # New unified chunk fields
        "nl_description": source.get("nl_description", source.get("snippet", "")),
        "code_content": source.get("code_content", ""),
        "entity_name": source.get("entity_name", ""),
        "entity_kind": source.get("entity_kind", "unknown"),
        "language": source.get("language", "unknown"),
        "programming_language": source.get("programming_language", "unknown"),
        "has_code": source.get("has_code", False),
        "ast_status": source.get("ast_status", "unknown"),
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_documents(
    query: str,
    top_k: int = 5,
    settings: AppSettings | None = None,
) -> list[dict]:
    """Search incidents by keyword match in title/snippet."""
    settings = settings or AppSettings()
    client = get_es_client(settings)
    index_name = settings.es_index_name

    body: dict[str, Any] = {
        "size": top_k,
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["title^2", "snippet", "tags"],
                "type": "best_fields",
            }
        },
    }

    try:
        response = client.search(index=index_name, body=body)
    except NotFoundError:
        logger.warning("ES index '%s' not found", index_name)
        return []
    except Exception as e:
        logger.warning("ES search failed: %s", e)
        return []

    hits = response.get("hits", {}).get("hits", [])
    results: list[dict] = []
    for hit in hits:
        source = hit.get("_source", {})
        score = float(hit.get("_score", 0))
        if score <= 0:
            continue
        results.append(_es_hit_to_legacy_result(source, score))

    return results


def search_unified(
    query: str,
    top_k: int = 5,
    code_metadata: list[dict] | None = None,
    settings: AppSettings | None = None,
) -> list[dict]:
    """Unified keyword search: NL + code_content matching with language boost.

    Language matching is a should+boost, not a filter — does not exclude
    other-language incidents.
    """
    settings = settings or AppSettings()
    client = get_es_client(settings)
    index_name = settings.es_index_name

    should_clauses: list[dict[str, Any]] = [
        # NL matching (high weight)
        {
            "multi_match": {
                "query": query,
                "fields": ["nl_description^3", "title^2", "section_title"],
                "type": "best_fields",
            }
        },
        # Code full-text matching
        {
            "multi_match": {
                "query": query,
                "fields": ["code_content^1.5", "signature^0.5"],
                "type": "best_fields",
            }
        },
    ]

    # Language boost (should, not filter)
    if code_metadata:
        languages = list(
            {e.get("language") for e in code_metadata if e.get("language")}
        )
        if languages:
            should_clauses.append({"terms": {"language": languages, "boost": 2}})

    body: dict[str, Any] = {
        "size": top_k,
        "query": {"bool": {"should": should_clauses}},
    }

    try:
        response = client.search(index=index_name, body=body)
    except NotFoundError:
        logger.warning("ES index '%s' not found", index_name)
        return []
    except Exception as e:
        logger.warning("ES unified search failed: %s", e)
        return []

    hits = response.get("hits", {}).get("hits", [])
    results: list[dict] = []
    for hit in hits:
        source = hit.get("_source", {})
        score = float(hit.get("_score", 0))
        if score <= 0:
            continue
        results.append(_es_hit_to_unified_result(source, score))

    return results
