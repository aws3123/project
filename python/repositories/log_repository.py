from __future__ import annotations

from threading import RLock
from typing import Dict, List

from repositories.base import LogRepositoryProtocol
from schemas.domain.log import NodeLog


class InMemoryLogRepository(LogRepositoryProtocol):
    def __init__(self) -> None:
        self._logs: Dict[str, List[NodeLog]] = {}
        self._lock = RLock()

    def append(self, log: NodeLog) -> NodeLog:
        with self._lock:
            self._logs.setdefault(log.task_id, []).append(log)
        return log

    def list(self, task_id: str) -> list[NodeLog]:
        with self._lock:
            return [log.model_copy(deep=True) for log in self._logs.get(task_id, [])]

    def reset(self) -> None:
        with self._lock:
            self._logs.clear()
