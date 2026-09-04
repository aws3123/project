from __future__ import annotations

from sqlalchemy import select

from repositories.base import TaskRepositoryProtocol
from repositories.db import cache_task_snapshot, get_cached_task_snapshot, get_session
from repositories.mappers import apply_task_updates, task_to_model, task_to_schema
from repositories.sqlalchemy_models import Base, ReviewTaskModel
from schemas.task import ReviewTask


class SQLTaskRepository(TaskRepositoryProtocol):
    def __init__(self, session_factory=get_session) -> None:
        self._session_factory = session_factory
        session = self._session_factory()
        try:
            Base.metadata.create_all(session.get_bind())
        finally:
            session.close()

    def save(self, task: ReviewTask) -> ReviewTask:
        session = self._session_factory()
        try:
            model = task_to_model(task)
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
            apply_task_updates(model, updates)
            session.add(model)
            session.commit()
            task = task_to_schema(model)
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
            task = task_to_schema(model)
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
