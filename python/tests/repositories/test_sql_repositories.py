"""Stage C SQL repository tests (using sqlite + in-memory redis stub)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import AppSettings
from repositories import db as db_module
from repositories.log_repository_sql import SQLLogRepository
from repositories.result_repository_sql import SQLResultRepository
from repositories.task_repository_sql import SQLTaskRepository
from schemas.api.request import ReviewRequest
from schemas.api.result import Recommendation, ReviewResult, RiskBreakdown
from schemas.domain.enums import ReviewMode, TaskStatus
from schemas.domain.log import NodeLog
from schemas.domain.task import ReviewTask
from services.task_service import TaskService


class _FakeRedis:
    def __init__(self):
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value

    def get(self, key: str):
        return self._store.get(key)


def _patch_sqlite(monkeypatch):
    settings = AppSettings(mysql_url="sqlite:///:memory:", persistence_backend="sql")
    engine = create_engine(settings.mysql_url)
    factory = sessionmaker(bind=engine)

    redis_client = _FakeRedis()
    monkeypatch.setattr(db_module, "get_engine", lambda settings_arg=None: engine)
    monkeypatch.setattr(
        db_module, "get_session_factory", lambda settings_arg=None: factory
    )
    monkeypatch.setattr(db_module, "get_session", lambda settings_arg=None: factory())
    monkeypatch.setattr(
        db_module, "get_redis_client", lambda settings_arg=None: redis_client
    )


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


def test_sql_task_repository_roundtrip(monkeypatch):
    _patch_sqlite(monkeypatch)
    repo = SQLTaskRepository()
    task = _task("t1")
    repo.save(task)
    stored = repo.get("t1")
    assert stored is not None
    assert stored.status == TaskStatus.QUEUED
    repo.update("t1", status=TaskStatus.PROCESSING)
    assert repo.get("t1").status == TaskStatus.PROCESSING


def test_sql_task_repository_save_serializes_uuid_payload(monkeypatch):
    _patch_sqlite(monkeypatch)
    repo = SQLTaskRepository()
    service = TaskService(repo)
    request = ReviewRequest(
        projectId="p1", repo="repo", branch="main", files=[], mode=ReviewMode.SYNC
    )

    task = service.enqueue(request)

    assert task.id
    stored = repo.get(task.id)
    assert stored is not None
    assert stored.payload["taskId"] == str(request.taskId)


def test_sql_task_repository_update_serializes_uuid_payload(monkeypatch):
    _patch_sqlite(monkeypatch)
    repo = SQLTaskRepository()
    task = _task("t-uuid")
    repo.save(task)

    request = ReviewRequest(
        projectId="p1", repo="repo", branch="main", files=[], mode=ReviewMode.SYNC
    )
    updated = repo.update("t-uuid", payload=request.model_dump(by_alias=True))

    assert updated is not None
    stored = repo.get("t-uuid")
    assert stored is not None
    assert stored.payload["taskId"] == str(request.taskId)


def test_sql_result_repository_roundtrip(monkeypatch):
    _patch_sqlite(monkeypatch)
    repo = SQLResultRepository()
    result = _result("t2")
    repo.save(result)
    stored = repo.get("t2")
    assert stored is not None
    assert stored.riskScore == 5


def test_sql_log_repository_roundtrip(monkeypatch):
    _patch_sqlite(monkeypatch)
    repo = SQLLogRepository()
    log = NodeLog(
        task_id="t3",
        node="diff",
        input={"a": 1},
        output={"b": 2},
        duration_ms=5,
        status="SUCCEEDED",
        timestamp=datetime.now(UTC),
    )
    repo.append(log)
    logs = repo.list("t3")
    assert len(logs) == 1
    assert logs[0].node == "diff"
