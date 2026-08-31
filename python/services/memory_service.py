from __future__ import annotations

import json
import logging
from datetime import datetime

from config.settings import AppSettings
from repositories.db import get_redis_client

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 7200
MEMORY_KEY_PREFIX = "memory:"


class MemoryService:
    """Manages session memory snapshots in Redis."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()

    def _redis_key(self, session_id: str) -> str:
        return f"{MEMORY_KEY_PREFIX}{session_id}"

    def load_session_memory(self, session_id: str | None) -> dict:
        """Load memory context for a session from Redis.

        Returns the stored memory context dict, or empty dict if none exists
        or Redis is unavailable.
        """
        if not session_id:
            return {}

        try:
            client = get_redis_client(self._settings)
            raw = client.get(self._redis_key(session_id))
            if not raw:
                logger.debug("No session memory found for session_id=%s", session_id)
                return {}
            data = json.loads(raw)
            logger.info(
                "Loaded session memory for session_id=%s version=%s",
                session_id,
                data.get("memory_version"),
            )
            return data.get("memory_context") or {}
        except Exception:
            logger.warning(
                "Failed to load session memory for session_id=%s, continuing with empty context",
                session_id,
                exc_info=True,
            )
            return {}

    def save_session_memory(
        self,
        session_id: str | None,
        updates: dict,
        version: str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """Persist proposed memory updates to Redis.

        Args:
            session_id: Session identifier.
            updates: Memory updates dict (e.g. proposed_memory_updates).
            version: Optional monotonic memory version for conflict detection.
            ttl_seconds: Redis key TTL in seconds.
        """
        if not session_id:
            return

        if not updates:
            return

        try:
            snapshot = {
                "memory_context": updates,
                "memory_version": version or "",
                "updated_at": datetime.now().isoformat(),
            }
            client = get_redis_client(self._settings)
            client.setex(
                self._redis_key(session_id),
                ttl_seconds,
                json.dumps(snapshot, ensure_ascii=False),
            )
            logger.info(
                "Saved session memory for session_id=%s version=%s fields=%s",
                session_id,
                version,
                list(updates.keys()),
            )
        except Exception:
            logger.warning(
                "Failed to save session memory for session_id=%s",
                session_id,
                exc_info=True,
            )

    def delete_session_memory(self, session_id: str | None) -> None:
        """Remove a session memory snapshot from Redis."""
        if not session_id:
            return
        try:
            client = get_redis_client(self._settings)
            client.delete(self._redis_key(session_id))
            logger.info("Deleted session memory for session_id=%s", session_id)
        except Exception:
            logger.warning(
                "Failed to delete session memory for session_id=%s",
                session_id,
                exc_info=True,
            )
