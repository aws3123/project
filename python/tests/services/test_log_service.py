"""LogService unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

from repositories.log_repository import InMemoryLogRepository
from schemas.log import NodeLog
from services.log_service import LogService


def make_log(status: str = "OK", output: dict | None = None) -> NodeLog:
    return NodeLog(
        task_id="task-1",
        node="diff",
        input={"path": "a.py"},
        output=output or {"ok": True},
        duration_ms=12,
        status=status,
        timestamp=datetime.now(UTC),
    )


def test_append_and_list_logs_with_hook():
    repo = InMemoryLogRepository()
    hook = Mock()
    service = LogService(repo, telemetry=hook)

    log = make_log()
    service.append(log)
    logs = service.list_by_task("task-1")

    assert len(logs) == 1
    hook.record_node.assert_called_once()


def test_append_failure_triggers_error_hook():
    repo = InMemoryLogRepository()
    hook = Mock()
    service = LogService(repo, telemetry=hook)

    log = make_log(status="FAILED", output={"error": "timeout"})
    service.append(log)

    hook.record_error.assert_called_once()
    hook.record_node.assert_called_once()
