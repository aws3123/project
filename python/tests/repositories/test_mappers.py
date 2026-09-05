"""Unit tests for repositories/mappers.py (ORM <-> DTO conversion)."""

from __future__ import annotations

from datetime import UTC, datetime

from repositories import mappers
from repositories.sqlalchemy_models import (
    NodeLogModel,
    ReviewResultModel,
    ReviewTaskModel,
)
from schemas.api.request import ReviewRequest
from schemas.api.result import Recommendation, ReviewResult, RiskBreakdown
from schemas.domain.enums import ReviewMode, TaskStatus
from schemas.domain.log import NodeLog
from schemas.domain.task import ReviewTask


def _task(task_id: str = "t1") -> ReviewTask:
    req = ReviewRequest(
        projectId="p1", repo="repo", branch="main", files=[], mode=ReviewMode.SYNC
    )
    return ReviewTask(
        id=task_id,
        project_id=req.projectId,
        status=TaskStatus.QUEUED,
        payload=req.model_dump(mode="json"),
        mode=req.mode,
        trace_id=req.traceId or f"trace-{task_id}",
    )


def _result(task_id: str = "t1") -> ReviewResult:
    return ReviewResult(
        taskId=task_id,
        status=TaskStatus.SUCCEEDED,
        riskScore=5,
        riskBreakdown=[RiskBreakdown(dimension="style", score=5)],
        recommendations=[Recommendation(title="ok", detail="ok")],
        traceId=f"trace-{task_id}",
        mode="SYNC",
        reportUrl="reports/t1.json",
    )


def test_serialize_payload_plain_dict():
    assert mappers.serialize_payload({"a": 1}) == '{"a": 1}'


def test_serialize_payload_pydantic_model():
    req = ReviewRequest(
        projectId="p1", repo="repo", branch="main", files=[], mode=ReviewMode.SYNC
    )
    dumped = req.model_dump(mode="json")
    serialized = mappers.serialize_payload(dumped)
    assert "taskId" in serialized


def test_task_roundtrip_model_to_schema():
    task = _task("t-roundtrip")
    model = mappers.task_to_model(task)
    assert isinstance(model, ReviewTaskModel)
    assert model.status == "QUEUED"
    assert model.mode == "SYNC"
    restored = mappers.task_to_schema(model)
    assert restored.id == task.id
    assert restored.status == TaskStatus.QUEUED
    assert restored.mode == ReviewMode.SYNC
    assert restored.payload == task.payload


def test_apply_task_updates():
    task = _task("t-update")
    model = mappers.task_to_model(task)
    mappers.apply_task_updates(
        model, {"status": TaskStatus.PROCESSING, "retry_count": 2}
    )
    assert model.status == "PROCESSING"
    assert model.retry_count == 2


def test_result_roundtrip_model_to_schema():
    result = _result("t-res")
    model = mappers.result_to_model(result)
    assert isinstance(model, ReviewResultModel)
    assert model.status == "SUCCEEDED"
    restored = mappers.result_to_schema(model)
    assert restored.taskId == "t-res"
    assert restored.riskScore == 5
    assert len(restored.riskBreakdown) == 1


def test_log_roundtrip():
    log = NodeLog(
        task_id="t-log",
        node="diff",
        input={"a": 1},
        output={"b": 2},
        duration_ms=5,
        status="SUCCEEDED",
        timestamp=datetime.now(UTC),
    )
    model = mappers.log_to_model(log)
    assert isinstance(model, NodeLogModel)
    restored = mappers.log_to_schema(model.payload)
    assert restored.node == "diff"
    assert restored.duration_ms == 5
