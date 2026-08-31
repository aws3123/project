from __future__ import annotations

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ReviewTaskModel(Base):
    __tablename__ = "review_task"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False)
    payload = Column(Text, nullable=False)
    mode = Column(String(16), nullable=False)
    retry_count = Column(Integer, nullable=False, default=0)
    trace_id = Column(String(128), nullable=False)


class ReviewResultModel(Base):
    __tablename__ = "review_result"

    task_id = Column(String(64), primary_key=True)
    status = Column(String(32), nullable=False)
    payload = Column(Text, nullable=False)


class NodeLogModel(Base):
    __tablename__ = "node_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False)
