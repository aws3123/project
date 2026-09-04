"""Tests for repository protocol compliant in-memory implementations."""

from __future__ import annotations

from datetime import UTC, datetime

from repositories.log_repository import InMemoryLogRepository
from repositories.result_repository import InMemoryResultRepository
from repositories.task_repository import InMemoryTaskRepository
from schemas.domain.enums import ReviewMode, TaskStatus
from schemas.domain.log import NodeLog
from schemas.api.request import ReviewRequest
from schemas.api.result import Recommendation, ReviewResult, RiskBreakdown
from schemas.domain.task import ReviewTask


def build_task(task_id: str = "task-1") -> ReviewTask:
    request = ReviewRequest(
        projectId="demo",
        repo="git@example.com/demo.git",
        branch="main",
        files=[],
        mode=ReviewMode.SYNC,
    )
    return ReviewTask(
        id=task_id,
        project_id=request.projectId,
        status=TaskStatus.QUEUED,
        payload=request.model_dump(by_alias=True),
        mode=request.mode,
        trace_id=request.traceId or f"trace-{task_id}",
    )


def build_result(task_id: str = "task-1") -> ReviewResult:
    return ReviewResult(
        taskId=task_id,
        status=TaskStatus.SUCCEEDED,
        riskScore=42,
        riskBreakdown=[RiskBreakdown(dimension="style", score=10)],
        recommendations=[Recommendation(title="noop", detail="noop")],
        traceId=f"trace-{task_id}",
        mode="SYNC",
    )


def test_task_repository_protocol_roundtrip():
    repo = InMemoryTaskRepository()
    task = build_task()
    repo.save(task)
    stored = repo.get(task.id)
    assert stored is not None
    assert stored.status == TaskStatus.QUEUED

    repo.update(task.id, status=TaskStatus.PROCESSING)
    updated = repo.get(task.id)
    assert updated.status == TaskStatus.PROCESSING

    assert repo.list_ids() == [task.id]


def test_result_repository_protocol_roundtrip():
    repo = InMemoryResultRepository()
    result = build_result()
    repo.save(result)
    stored = repo.get(result.taskId)
    assert stored is not None
    assert stored.riskScore == result.riskScore


def test_log_repository_preserves_order_and_copy():
    repo = InMemoryLogRepository()
    log1 = NodeLog(
        task_id="task-1",
        node="diff",
        input={"step": 1},
        output={"ok": True},
        duration_ms=5,
        status="OK",
        timestamp=datetime.now(UTC),
    )
    log2 = NodeLog(
        task_id="task-1",
        node="rag",
        input={"step": 2},
        output={"ok": True},
        duration_ms=10,
        status="OK",
        timestamp=datetime.now(UTC),
    )
    repo.append(log1)
    repo.append(log2)

    logs = repo.list("task-1")
    assert [log.node for log in logs] == ["diff", "rag"]
    assert logs[0] is not log1
    assert logs[1] is not log2
