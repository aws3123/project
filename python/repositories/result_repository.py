from __future__ import annotations

from threading import RLock
from typing import Dict

from repositories.base import ResultRepositoryProtocol
from schemas.result import ReviewResult


class InMemoryResultRepository(ResultRepositoryProtocol):
    def __init__(self) -> None:
        self._results: Dict[str, ReviewResult] = {}
        self._lock = RLock()

    def save(self, result: ReviewResult) -> ReviewResult:
        with self._lock:
            self._results[result.taskId] = result
        return result

    def get(self, task_id: str) -> ReviewResult | None:
        with self._lock:
            result = self._results.get(task_id)
            return result.model_copy(deep=True) if result else None

    def reset(self) -> None:
        with self._lock:
            self._results.clear()
