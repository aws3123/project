from __future__ import annotations

"""Thread-safe in-memory implementation of the task repository protocol."""

from threading import RLock
from typing import Dict

from repositories.base import TaskRepositoryProtocol
from schemas.domain.task import ReviewTask


class InMemoryTaskRepository(TaskRepositoryProtocol):
    """Stores review tasks without external dependencies."""

    def __init__(self) -> None:
        self._tasks: Dict[str, ReviewTask] = {}
        self._lock = RLock()

    def save(self, task: ReviewTask) -> ReviewTask:
        with self._lock:
            self._tasks[task.id] = task
        return task

    def update(self, task_id: str, **updates) -> ReviewTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            updated = task.model_copy(update=updates)
            self._tasks[task_id] = updated
            return updated

    def get(self, task_id: str) -> ReviewTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task else None

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._tasks.keys())

    def reset(self) -> None:
        with self._lock:
            self._tasks.clear()
