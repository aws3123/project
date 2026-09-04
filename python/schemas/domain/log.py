"""
节点日志数据模型
=================

作用：
    定义 LangGraph 流水线中每个节点（Node）执行时的遥测日志结构。

什么是 LangGraph 节点？
    本项目的代码审查流程是用 LangGraph 框架编排的"有向图"。
    图中的每个节点负责一个具体的步骤（比如"分类"、"RAG 检索"、"打分"等）。
    每次执行一个节点，都会产生一条 NodeLog 记录，方便追踪和调试。
"""

# datetime 用于记录日志产生的精确时间
from datetime import datetime

# BaseModel 是 Pydantic 的数据模型基类
from pydantic import BaseModel


class NodeLog(BaseModel):
    """表示 LangGraph 中某个节点执行时产生的遥测日志。

    每条日志记录了：谁执行的（task_id）、哪个节点（node）、
    输入了什么（input）、输出了什么（output）、花了多久（duration_ms）、
    执行状态（status）、什么时间（timestamp）。
    """

    # 任务 ID —— 标识这次日志属于哪个审查任务
    task_id: str
    # 节点名称 —— 比如 "classifier"、"rag"、"scoring" 等
    node: str
    # 节点的输入数据（传给这个节点的参数）
    input: dict
    # 节点的输出数据（这个节点返回的结果）
    output: dict
    # 执行耗时（毫秒），用于性能监控
    duration_ms: int
    # 执行状态：通常是 "success" 或 "error"
    status: str
    # 日志产生的时间戳
    timestamp: datetime

    # Pydantic 模型配置
    model_config = {
        "populate_by_name": True,
    }


"""Schemas for structured telemetry logs produced during graph execution."""

from datetime import datetime

from pydantic import BaseModel


class NodeLog(BaseModel):
    """Represents the telemetry emitted for each LangGraph node run."""

    task_id: str
    node: str
    input: dict
    output: dict
    duration_ms: int
    status: str
    timestamp: datetime

    model_config = {
        "populate_by_name": True,
    }
