from __future__ import annotations

from repositories.base import ResultRepositoryProtocol
from repositories.db import get_session
from repositories.mappers import result_to_model, result_to_schema
from repositories.sqlalchemy_models import Base, ReviewResultModel
from schemas.result import ReviewResult


class SQLResultRepository(ResultRepositoryProtocol):
    def __init__(self, session_factory=get_session) -> None:
        self._session_factory = session_factory
        session = self._session_factory()
        try:
            Base.metadata.create_all(session.get_bind())
        finally:
            session.close()

    def save(self, result: ReviewResult) -> ReviewResult:
        session = self._session_factory()
        try:
            model = result_to_model(result)
            session.merge(model)
            session.commit()
            return result
        finally:
            session.close()

    def get(self, task_id: str) -> ReviewResult | None:
        session = self._session_factory()
        try:
            model = session.get(ReviewResultModel, task_id)
            if not model:
                return None
            return result_to_schema(model)
        finally:
            session.close()
