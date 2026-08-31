from __future__ import annotations

import json
import logging

from config.settings import AppSettings
from repositories.db import get_redis_client

logger = logging.getLogger(__name__)

KEY_PREFIX = "ckpt:"
DEFAULT_TTL_SECONDS = 86400  # 24h, aligned with TaskStatus Redis cache


class CheckpointService:
    """Manages pipeline execution checkpoints in Redis."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()

    def _redis_key(self, task_id: str) -> str:
        return f"{KEY_PREFIX}{task_id}"

    def save(self, task_id: str, checkpoint: dict) -> None:
        """Persist a checkpoint to Redis.

        Args:
            task_id: Task identifier.
            checkpoint: Checkpoint dict containing state, completed_phases,
                        and optionally parallel_results / phase_input.
        """
        try:
            client = get_redis_client(self._settings)
            client.setex(
                self._redis_key(task_id),
                DEFAULT_TTL_SECONDS,
                json.dumps(checkpoint, ensure_ascii=False, default=str),
            )
            logger.info(
                "Saved checkpoint for task_id=%s completed_phases=%s",
                task_id,
                checkpoint.get("completed_phases"),
            )
        except Exception:
            logger.warning(
                "Failed to save checkpoint for task_id=%s",
                task_id,
                exc_info=True,
            )

    def load(self, task_id: str) -> dict | None:
        """Load a checkpoint from Redis.

        Returns the checkpoint dict, or None if not found or Redis is unavailable.
        """
        try:
            client = get_redis_client(self._settings)
            raw = client.get(self._redis_key(task_id))
            if not raw:
                logger.debug("No checkpoint found for task_id=%s", task_id)
                return None
            data = json.loads(raw)
            logger.info(
                "Loaded checkpoint for task_id=%s completed_phases=%s",
                task_id,
                data.get("completed_phases"),
            )
            return data
        except Exception:
            logger.warning(
                "Failed to load checkpoint for task_id=%s",
                task_id,
                exc_info=True,
            )
            return None

    def delete(self, task_id: str) -> None:
        """Delete a checkpoint after successful pipeline completion."""
        try:
            client = get_redis_client(self._settings)
            client.delete(self._redis_key(task_id))
            logger.info("Deleted checkpoint for task_id=%s", task_id)
        except Exception:
            logger.warning(
                "Failed to delete checkpoint for task_id=%s",
                task_id,
                exc_info=True,
            )
