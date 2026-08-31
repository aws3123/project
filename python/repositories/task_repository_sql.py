from __future__ import annotations

import json
from pydantic import BaseModel

from sqlalchemy import select

from repositories.base import TaskRepositoryProtocol
from repositories.db import cache_task_snapshot, get_cached_task_snapshot, get_session
from repositories.sqlalchemy_models import Base, ReviewTaskModel
from schemas.enums import ReviewMode, TaskStatus
from schemas.task import ReviewTask


class SQLTaskRepository(TaskRepositoryProtocol):
    def __init__(self, session_factory=get_session) -> None:
        self._session_factory = session_factory
        session = self._session_factory()
        try:
            Base.metadata.create_all(session.get_bind())
        finally:
            session.close()

    @staticmethod
    def _serialize_payload(payload: dict) -> str:
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False, default=str)

    def save(self, task: ReviewTask) -> ReviewTask:
        session = self._session_factory()
        try:
            model = ReviewTaskModel(
                id=task.id,
                project_id=task.project_id,
                status=task.status.value,
                payload=self._serialize_payload(task.payload),
                mode=task.mode.value,
                retry_count=task.retry_count,
                trace_id=task.trace_id,
            )
            session.merge(model)
            session.commit()
            cache_task_snapshot(task.id, task.model_dump(mode="json"))
            return task
        finally:
            session.close()

    def update(self, task_id: str, **updates) -> ReviewTask | None:
        session = self._session_factory()
        try:
            model = session.get(ReviewTaskModel, task_id)
            if not model:
                return None
            if "status" in updates:
                status = updates["status"]
                model.status = status.value if hasattr(status, "value") else str(status)
            if "payload" in updates:
                model.payload = self._serialize_payload(updates["payload"])
            if "retry_count" in updates:
                model.retry_count = int(updates["retry_count"])
            session.add(model)
            session.commit()
            task = self._to_schema(model)
            cache_task_snapshot(task.id, task.model_dump(mode="json"))
            return task
        finally:
            session.close()

    def get(self, task_id: str) -> ReviewTask | None:
        cached = get_cached_task_snapshot(task_id)
        if cached:
            return ReviewTask(**cached)
        session = self._session_factory()
        try:
            model = session.get(ReviewTaskModel, task_id)
            if not model:
                return None
            task = self._to_schema(model)
            cache_task_snapshot(task.id, task.model_dump(mode="json"))
            return task
        finally:
            session.close()

    def list_ids(self) -> list[str]:
        session = self._session_factory()
        try:
            rows = session.execute(select(ReviewTaskModel.id)).all()
            return [row[0] for row in rows]
        finally:
            session.close()

    @staticmethod
    def _to_schema(model: ReviewTaskModel) -> ReviewTask:
        return ReviewTask(
            id=model.id,
            project_id=model.project_id,
            status=TaskStatus(model.status),
            payload=json.loads(model.payload),
            mode=ReviewMode(model.mode),
            retry_count=model.retry_count,
            trace_id=model.trace_id,
        )
