from __future__ import annotations

from sqlalchemy import select

from repositories.base import LogRepositoryProtocol
from repositories.db import get_session
from repositories.mappers import log_to_model, log_to_schema
from repositories.sqlalchemy_models import Base, NodeLogModel
from schemas.domain.log import NodeLog


class SQLLogRepository(LogRepositoryProtocol):
    def __init__(self, session_factory=get_session) -> None:
        self._session_factory = session_factory
        session = self._session_factory()
        try:
            Base.metadata.create_all(session.get_bind())
        finally:
            session.close()

    def append(self, log: NodeLog) -> NodeLog:
        session = self._session_factory()
        try:
            model = log_to_model(log)
            session.add(model)
            session.commit()
            return log
        finally:
            session.close()

    def list(self, task_id: str) -> list[NodeLog]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(NodeLogModel.payload).where(NodeLogModel.task_id == task_id).order_by(NodeLogModel.id.asc())
            ).all()
            return [log_to_schema(row[0]) for row in rows]
        finally:
            session.close()
