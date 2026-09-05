"""
审查任务数据模型
=================

作用：
    定义"审查任务"在持久化层（数据库/内存）中的数据结构。
    一个"任务"就是一次代码审查的工作单元，从创建到完成都有对应的状态。

和 ReviewRequest 的区别：
    ReviewRequest 是"前端发来的请求"，ReviewTask 是"系统内部追踪的任务"。
    就像你在餐厅点了一道菜（ReviewRequest），厨房会生成一个工单（ReviewTask）来追踪进度。
"""

# BaseModel 是 Pydantic 的数据模型基类
from pydantic import BaseModel

# 导入枚举类型：审查模式和任务状态
from schemas.domain.enums import ReviewMode, TaskStatus


class ReviewTask(BaseModel):
    """表示一个已入队或正在运行的审查任务的元数据。

    生命周期：
        1. 收到审查请求 → 创建 ReviewTask（状态=QUEUED）
        2. 开始处理     → 更新状态为 PROCESSING
        3. 处理完成     → 更新状态为 SUCCEEDED / FAILED / NEED_REVIEW
    """

    # 任务唯一标识（字符串形式的 UUID）
    id: str
    # 所属项目的标识
    project_id: str
    # 任务当前状态（排队中/处理中/成功/失败/需人工复核）
    status: TaskStatus
    # 任务的原始请求数据（即 ReviewRequest 的 JSON 形式）
    # 用 dict 存储是因为这里需要灵活保存各种请求参数
    payload: dict
    # 审查模式（同步/异步）
    mode: ReviewMode
    # 重试次数：如果任务失败，系统会自动重试，这里记录已经重试了几次
    retry_count: int = 0
    # 链路追踪 ID，用于在日志中追踪这次任务的完整调用链
    trace_id: str

    # Pydantic 模型配置
    model_config = {
        # 允许通过字段名或别名来填充数据
        "populate_by_name": True,
    }


"""Schemas describing review tasks tracked in persistence layers."""

from pydantic import BaseModel

from schemas.domain.enums import ReviewMode, TaskStatus


class ReviewTask(BaseModel):
    """Represents metadata about a queued or running task."""

    id: str
    project_id: str
    status: TaskStatus
    payload: dict
    mode: ReviewMode
    retry_count: int = 0
    trace_id: str

    model_config = {
        "populate_by_name": True,
    }
