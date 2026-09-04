"""ORM 模型与 DTO（pydantic schema）之间的转换 —— 收口所有序列化逻辑。

职责：
    集中管理 SQL 仓储层与数据库 ORM 模型之间的双向映射，
    避免每个 *_repository_sql.py 各自内联一份序列化实现。

设计：
    函数式（模块级纯函数），与项目的轻量风格一致。
    仓储只负责 session 管理与读写，字段映射全部委托本模块。
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from repositories.sqlalchemy_models import (
    NodeLogModel,
    ReviewResultModel,
    ReviewTaskModel,
)
from schemas.api.result import ReviewResult
from schemas.domain.enums import ReviewMode, TaskStatus
from schemas.domain.log import NodeLog
from schemas.domain.task import ReviewTask


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------
def serialize_payload(payload: dict | BaseModel) -> str:
    """任意 payload（原始请求 dict 或 pydantic 模型）→ JSON 字符串。"""
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, default=str)


def task_to_model(task: ReviewTask) -> ReviewTaskModel:
    """任务 DTO → ORM 模型（供 save/merge）。"""
    return ReviewTaskModel(
        id=task.id,
        project_id=task.project_id,
        status=task.status.value,
        payload=serialize_payload(task.payload),
        mode=task.mode.value,
        retry_count=task.retry_count,
        trace_id=task.trace_id,
    )


def task_to_schema(model: ReviewTaskModel) -> ReviewTask:
    """ORM 模型 → 任务 DTO（供 get/update 返回）。"""
    return ReviewTask(
        id=model.id,
        project_id=model.project_id,
        status=TaskStatus(model.status),
        payload=json.loads(model.payload),
        mode=ReviewMode(model.mode),
        retry_count=model.retry_count,
        trace_id=model.trace_id,
    )


def apply_task_updates(model: ReviewTaskModel, updates: dict) -> None:
    """将 update() 的字段变更应用到 ORM 模型上（status/payload/retry_count）。"""
    if "status" in updates:
        status = updates["status"]
        model.status = status.value if hasattr(status, "value") else str(status)
    if "payload" in updates:
        model.payload = serialize_payload(updates["payload"])
    if "retry_count" in updates:
        model.retry_count = int(updates["retry_count"])


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
def result_to_model(result: ReviewResult) -> ReviewResultModel:
    """审查结果 DTO → ORM 模型（供 save/merge）。"""
    return ReviewResultModel(
        task_id=result.taskId,
        status=result.status.value,
        payload=result.model_dump_json(),
    )


def result_to_schema(model: ReviewResultModel) -> ReviewResult:
    """ORM 模型 → 审查结果 DTO（供 get 返回）。"""
    return ReviewResult(**json.loads(model.payload))


# ---------------------------------------------------------------------------
# NodeLog
# ---------------------------------------------------------------------------
def log_to_model(log: NodeLog) -> NodeLogModel:
    """节点日志 DTO → ORM 模型（供 append）。"""
    return NodeLogModel(task_id=log.task_id, payload=log.model_dump_json())


def log_to_schema(payload_json: str) -> NodeLog:
    """节点日志 payload JSON 字符串 → DTO（供 list 还原）。"""
    return NodeLog(**json.loads(payload_json))
