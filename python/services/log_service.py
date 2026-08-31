from __future__ import annotations

from repositories.base import LogRepositoryProtocol
from schemas.log import NodeLog
from telemetry.hooks import TelemetryHook


class LogService:
    def __init__(self, repository: LogRepositoryProtocol, telemetry: TelemetryHook | None = None) -> None:
        self._repo = repository
        self._telemetry = telemetry

    def append(self, log: NodeLog) -> NodeLog:
        saved = self._repo.append(log)
        if self._telemetry:
            if log.status == "FAILED":
                self._telemetry.record_error(saved, RuntimeError(saved.output.get("error", "")))
            self._telemetry.record_node(saved)
        return saved

    def list_by_task(self, task_id: str) -> list[NodeLog]:
        return self._repo.list(task_id)
