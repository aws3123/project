from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

import chromadb
from chromadb.config import Settings

from config.settings import AppSettings
from repositories.db import _fetch_query_embedding


# Chroma's persistent client owns an internal HTTP transport.  Recreating a
# wrapper for every retrieval lets one wrapper close shared transport state
# while another concurrent retrieval is still using it.  Keep the client and
# collection alive for the whole worker process instead.
_client_lock = RLock()
_query_lock = RLock()
_chroma_clients: dict[str, Any] = {}
_incident_collections: dict[tuple[str, str], Any] = {}


def _chroma_path(settings: AppSettings) -> str:
    return str(Path(settings.chroma_path))


def _reset_chroma_cache() -> None:
    """Clear process caches. Intended for tests only."""
    with _client_lock:
        _chroma_clients.clear()
        _incident_collections.clear()


def get_chroma_client(settings: AppSettings | None = None):
    settings = settings or AppSettings()
    path = _chroma_path(settings)
    with _client_lock:
        client = _chroma_clients.get(path)
        if client is None:
            client = chromadb.PersistentClient(path=path, settings=Settings())
            _chroma_clients[path] = client
        return client


def get_incident_collection(settings: AppSettings | None = None):
    settings = settings or AppSettings()
    path = _chroma_path(settings)
    key = (path, settings.chroma_collection)
    with _client_lock:
        collection = _incident_collections.get(key)
        if collection is None:
            client = get_chroma_client(settings)
            collection = client.get_or_create_collection(
                name=settings.chroma_collection,
                configuration={"hnsw": {"space": "cosine"}},
                embedding_function=None,
            )
            _incident_collections[key] = collection
        return collection


def bootstrap_chromadb(settings: AppSettings | None = None):
    return get_incident_collection(settings)


def upsert_incident_rows(rows: list[dict], settings: AppSettings | None = None) -> None:
    settings = settings or AppSettings()
    collection = get_incident_collection(settings)

    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict] = []

    for row in rows:
        ids.append(str(row["id"]))
        documents.append(row["snippet"])
        embeddings.append([float(value) for value in row["embedding"]])
        metadata = {
            "title": row["title"],
            "source": row["source"],
            "service": row.get("service"),
        }
        tags = row.get("tags", [])
        if tags:
            metadata["tags"] = tags

        image_urls = row.get("image_urls", [])
        image_texts = row.get("image_texts", [])
        if image_urls:
            metadata["image_urls"] = json.dumps(image_urls, ensure_ascii=False)
            metadata["has_images"] = True
        if image_texts:
            metadata["image_texts"] = json.dumps(image_texts, ensure_ascii=False)

        metadatas.append(metadata)

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def upsert_unified_chunks(
    chunks: list[dict], settings: AppSettings | None = None
) -> None:
    """Write unified chunks (NL + code + AST metadata) to ChromaDB.

    Each chunk dict must contain:
        id, nl_description, code_content, embedding, doc_metadata, ast_metadata
    """
    settings = settings or AppSettings()
    collection = get_incident_collection(settings)

    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict] = []

    for chunk in chunks:
        chunk_id = str(chunk["id"])
        embed_text = f"{chunk['nl_description']}\n{chunk['code_content']}"
        ast_meta = chunk.get("ast_metadata", {})
        doc_meta = chunk.get("doc_metadata", {})

        metadata = {
            # Legacy fields (backward compatibility)
            "title": doc_meta.get("section_title", ""),
            "source": doc_meta.get("source_doc", "unknown"),
            "service": doc_meta.get("service"),
            # New unified chunk fields
            "nl_description": chunk["nl_description"],
            "code_content": chunk["code_content"],
            "entity_name": ast_meta.get("entity_name", ""),
            "entity_kind": ast_meta.get("entity_kind", "unknown"),
            "language": ast_meta.get("language", "unknown"),
            "programming_language": ast_meta.get("language", "unknown"),
            "has_code": bool(chunk["code_content"]),
            "ast_status": ast_meta.get("ast_status", "unknown"),
            "chunk_type": doc_meta.get("chunk_type", "code"),
            "page_start": doc_meta.get("page_start") or 0,
            "page_end": doc_meta.get("page_end") or 0,
        }

        tags = doc_meta.get("tags", [])
        if tags:
            metadata["tags"] = tags

        image_urls = doc_meta.get("image_urls", [])
        image_texts = doc_meta.get("image_texts", [])
        if image_urls:
            metadata["image_urls"] = json.dumps(image_urls, ensure_ascii=False)
            metadata["has_images"] = True
        if image_texts:
            metadata["image_texts"] = json.dumps(image_texts, ensure_ascii=False)
        image_relations = doc_meta.get("image_relations", [])
        image_bboxes = doc_meta.get("image_bboxes", [])
        if image_relations:
            metadata["image_relations"] = json.dumps(image_relations, ensure_ascii=False)
        if image_bboxes:
            metadata["image_bboxes"] = json.dumps(image_bboxes, ensure_ascii=False)

        ids.append(chunk_id)
        documents.append(embed_text)
        embeddings.append([float(v) for v in chunk["embedding"]])
        metadatas.append(metadata)

    if ids:
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )


def _score_from_distance(distance: float) -> float:
    return round(max(0.0, 1.0 - float(distance)), 6)


def _parse_image_json(raw: str | list) -> list:
    """Safely parse image_urls/image_texts from ChromaDB metadata."""
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []


def _chroma_hit_to_result(document: str, metadata: dict, distance: float) -> dict:
    """Build a unified result dict from a single ChromaDB query hit."""
    image_urls = _parse_image_json(metadata.get("image_urls", "[]"))
    image_texts = _parse_image_json(metadata.get("image_texts", "[]"))
    return {
        # Legacy fields
        "title": metadata.get("title", "unknown"),
        "snippet": document,
        "source": metadata.get("source", "chromadb"),
        "service": metadata.get("service"),
        "tags": metadata.get("tags", []),
        "image_urls": image_urls,
        "image_texts": image_texts,
        "score": _score_from_distance(distance),
        # New unified chunk fields (with defaults for backward compat)
        "nl_description": metadata.get("nl_description", document),
        "code_content": metadata.get("code_content", ""),
        "entity_name": metadata.get("entity_name", ""),
        "entity_kind": metadata.get("entity_kind", "unknown"),
        "language": metadata.get("language", "unknown"),
        "programming_language": metadata.get("programming_language", "unknown"),
        "has_code": metadata.get("has_code", False),
        "ast_status": metadata.get("ast_status", "unknown"),
        "chunk_type": metadata.get("chunk_type", "unknown"),
        "page_start": metadata.get("page_start") or None,
        "page_end": metadata.get("page_end") or None,
        "image_relations": _parse_image_json(metadata.get("image_relations", "[]")),
        "image_bboxes": _parse_image_json(metadata.get("image_bboxes", "[]")),
    }


def search_incidents_chromadb(
    query: str, top_k: int, settings: AppSettings | None = None
) -> list[dict]:
    settings = settings or AppSettings()
    collection = get_incident_collection(settings)
    query_embedding = _fetch_query_embedding(query, settings)
    # The embedded Chroma transport is not safe to close/reopen concurrently.
    # Serialising the very short local query protects that shared transport;
    # embedding and Elasticsearch recall still execute outside this lock.
    with _query_lock:
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

    documents = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances", [[]])[0]

    rows: list[dict] = []
    for document, metadata, distance in zip(
        documents, metadatas, distances, strict=False
    ):
        rows.append(_chroma_hit_to_result(document, metadata, distance))
    return rows


def search_by_embedding(
    query_embedding: list[float],
    top_k: int,
    settings: AppSettings | None = None,
) -> list[dict]:
    """Vector recall by pre-computed embedding, no language filter.

    Returns results with all unified chunk fields (same format as search_incidents_chromadb).
    """
    settings = settings or AppSettings()
    collection = get_incident_collection(settings)
    with _query_lock:
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

    documents = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances", [[]])[0]

    rows: list[dict] = []
    for document, metadata, distance in zip(
        documents, metadatas, distances, strict=False
    ):
        rows.append(_chroma_hit_to_result(document, metadata, distance))
    return rows
