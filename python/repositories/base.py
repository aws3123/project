from __future__ import annotations

from typing import Protocol

from schemas.api.result import ReviewResult
from schemas.domain.log import NodeLog
from schemas.domain.task import ReviewTask


class TaskRepositoryProtocol(Protocol):
    """Abstracts persistence for review tasks."""

    def save(self, task: ReviewTask) -> ReviewTask: ...

    def update(self, task_id: str, **updates) -> ReviewTask | None: ...

    def get(self, task_id: str) -> ReviewTask | None: ...

    def list_ids(self) -> list[str]: ...


class ResultRepositoryProtocol(Protocol):
    """Abstracts persistence for review results."""

    def save(self, result: ReviewResult) -> ReviewResult: ...

    def get(self, task_id: str) -> ReviewResult | None: ...


class LogRepositoryProtocol(Protocol):
    """Abstracts persistence for LangGraph node logs."""

    def append(self, log: NodeLog) -> NodeLog: ...

    def list(self, task_id: str) -> list[NodeLog]: ...
