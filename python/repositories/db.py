from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import AppSettings

logger = logging.getLogger(__name__)


def get_engine(settings: AppSettings | None = None):
    settings = settings or AppSettings()
    return create_engine(settings.mysql_url, pool_pre_ping=True)


def get_session_factory(settings: AppSettings | None = None):
    engine = get_engine(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session(settings: AppSettings | None = None) -> Session:
    factory = get_session_factory(settings)
    return factory()


def get_redis_client(settings: AppSettings | None = None):
    from redis import Redis

    settings = settings or AppSettings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_minio_client(settings: AppSettings | None = None):
    from minio import Minio
    from urllib3 import PoolManager, Retry

    settings = settings or AppSettings()
    endpoint = settings.minio_endpoint.replace("http://", "").replace("https://", "")
    secure = settings.minio_endpoint.startswith("https://")
    http_client = PoolManager(
        retries=Retry(total=0, connect=0, read=0, redirect=0),
        timeout=3,
    )
    return Minio(
        endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=secure,
        http_client=http_client,
    )


# Global embedding model cache (loaded once per process lifetime)
_embedding_model: Any | None = None


def _get_embedding_model(model_name: str = "microsoft/codebert-base"):
    """Lazy-load and cache the local sentence-transformer model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(model_name)
    return _embedding_model


def _fetch_query_embedding(query: str, settings: AppSettings) -> list[float]:
    encoder = _get_embedding_model(settings.embedding_model)
    emb = encoder.encode(query, normalize_embeddings=True)
    return emb.tolist()


def cache_task_snapshot(task_id: str, payload: dict, settings: AppSettings | None = None) -> None:
    client = get_redis_client(settings)
    client.set(f"task:{task_id}", json.dumps(payload, ensure_ascii=False), ex=86400)


def get_cached_task_snapshot(task_id: str, settings: AppSettings | None = None) -> dict | None:
    client = get_redis_client(settings)
    raw = client.get(f"task:{task_id}")
    if not raw:
        return None
    return json.loads(raw)
