"""
审查结果数据模型
=================

作用：
    定义代码审查完成后的"结果"数据结构，包括风险评分、详细发现、建议等。
    这些模型是审查流水线的最终输出，会被返回给前端或存入数据库。
"""

# Any 表示任意类型，List 表示列表
from typing import Any, List

# BaseModel 是 Pydantic 的数据模型基类
# Field 用于给字段添加约束（如范围限制）
from pydantic import BaseModel, Field

# 导入枚举类型
from .enums import RAGStatus, TaskStatus, Tier


# =============================================================================
# 风险维度细分模型 —— 某个具体维度的风险评分
# =============================================================================
class RiskBreakdown(BaseModel):
    """风险评分的维度细分。

    比如整体风险评分是 70 分，细分可能是：
      - 安全性: 80 分
      - 性能:   60 分
      - 可维护性: 50 分
    """
    # 维度名称，比如 "security"、"performance"
    dimension: str
    # 该维度的评分（0~100）。ge=0 表示最小值 0，le=100 表示最大值 100
    score: int = Field(ge=0, le=100)


# =============================================================================
# 改进建议模型
# =============================================================================
class Recommendation(BaseModel):
    """审查结果中的改进建议。

    每条建议有一个简短的标题和详细的说明。
    """
    # 建议标题，比如 "建议使用参数化查询"
    title: str
    # 建议的详细说明，解释为什么要改、怎么改
    detail: str


# =============================================================================
# 代码审查结果模型 —— 核心输出
# =============================================================================
class ReviewResult(BaseModel):
    """代码审查的最终结果，是整个审查流水线的核心输出。

    包含了风险评分、详细发现、改进建议、报告链接等完整信息。
    """

    # 任务 ID —— 标识这次审查结果属于哪个任务
    taskId: str
    # 任务状态（成功/失败/需人工复核）
    status: TaskStatus
    # 整体风险评分（0~100），0 表示无风险，100 表示极高风险
    riskScore: int = Field(ge=0, le=100)
    # 风险摘要（一句话概括审查发现的主要风险）
    riskSummary: str | None = None
    # 详细发现列表（每条是一个具体的风险发现描述）
    details: List[str] = Field(default_factory=list)
    # 各维度的风险评分细分（安全性、性能等）
    riskBreakdown: List[RiskBreakdown] = Field(default_factory=list)
    # 改进建议列表
    recommendations: List[Recommendation] = Field(default_factory=list)
    # 审查报告的 URL（报告通常以文件形式存储在 MinIO 中）
    reportUrl: str | None = None
    # 是否需要人工复核（AI 不确定时会标记为需要人工介入）
    needHumanReview: bool = False
    # RAG 检索状态（正常/降级），如果检索质量差，审查结果可能不够准确
    ragStatus: RAGStatus = RAGStatus.NORMAL
    # 审查层级（仅规则 / LLM 增强）
    tier: Tier = Tier.LLM_ENHANCED
    # 链路追踪 ID
    traceId: str
    # 审查模式（同步/异步）
    mode: str
    # 运行 ID，标识这次审查的运行实例
    # validation_alias="run_id" 表示 JSON 中可以用 run_id（下划线风格）来填充这个字段
    runId: str | None = Field(default=None, validation_alias="run_id")
    # 建议的记忆更新：审查过程中发现的新知识，可以更新到记忆系统中
    proposedMemoryUpdates: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="proposed_memory_updates",
    )

    model_config = {
        "populate_by_name": True,
    }


# =============================================================================
# 健康检查模型 —— 用于 /health 接口
# =============================================================================
class HealthComponent(BaseModel):
    """单个组件的健康状态。

    比如 MySQL 组件的健康状态：status="up" 或 status="down"。
    """
    # 状态：通常是 "up"（正常）或 "down"（异常）
    status: str
    # 附加说明，比如 "连接超时" 或 "版本 8.0"
    detail: str | None = None


class HealthStatus(BaseModel):
    """系统整体健康状态，汇总了所有关键组件的状态。

    调用 /health 接口时返回这个结构，运维人员可以一眼看到哪个组件出了问题。
    """
    # 整体状态：所有组件都正常时为 "healthy"，否则为 "degraded" 或 "unhealthy"
    overall: str
    # 各组件的健康状态
    mysql: HealthComponent     # MySQL 数据库
    redis: HealthComponent     # Redis 缓存
    minio: HealthComponent     # MinIO 对象存储
    vector: HealthComponent    # 向量数据库（ChromaDB）
    llm: HealthComponent       # 大语言模型服务


# =============================================================================
# 业务风险就绪检查模型 —— 用于业务风险接口的健康检查
# =============================================================================
class BusinessRiskReadinessComponent(BaseModel):
    """业务风险模块中单个组件的就绪状态。"""
    status: str
    detail: str | None = None


class BusinessRiskSourceReadinessStatus(BaseModel):
    """业务风险源处理模块的整体就绪状态。

    在处理业务风险请求之前，需要检查各个依赖组件是否就绪。
    """
    # 整体就绪状态
    overall: str
    # 路由组件是否就绪
    route: BusinessRiskReadinessComponent
    # 配置是否就绪
    config: BusinessRiskReadinessComponent
    # 持久化层是否就绪
    persistence: BusinessRiskReadinessComponent
    # LLM 服务是否就绪
    llm: BusinessRiskReadinessComponent


# =============================================================================
# 业务风险审查结果模型
# =============================================================================
class BusinessRiskResult(BaseModel):
    """业务风险审查的最终结果。

    和 ReviewResult 类似，但专门用于业务风险场景（如"订单金额超限"等）。
    """
    # 任务 ID
    taskId: str
    # 任务状态
    status: TaskStatus
    # 运行 ID（必须提供，用 validation_alias 支持下划线风格的输入）
    runId: str = Field(validation_alias="run_id")
    # 风险摘要
    riskSummary: str | None = None
    # 详细发现列表
    details: List[str] = Field(default_factory=list)
    # 建议的记忆更新
    proposedMemoryUpdates: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="proposed_memory_updates",
    )
    # 链路追踪 ID
    traceId: str | None = None
"""Schemas representing review results and scoring details."""

from typing import Any, List

from pydantic import BaseModel, Field

from .enums import RAGStatus, TaskStatus, Tier


class RiskBreakdown(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=100)


class Recommendation(BaseModel):
    title: str
    detail: str


class ReviewResult(BaseModel):
    taskId: str
    status: TaskStatus
    riskScore: int = Field(ge=0, le=100)
    riskSummary: str | None = None
    details: List[str] = Field(default_factory=list)
    riskBreakdown: List[RiskBreakdown] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)
    reportUrl: str | None = None
    needHumanReview: bool = False
    ragStatus: RAGStatus = RAGStatus.NORMAL
    tier: Tier = Tier.LLM_ENHANCED
    traceId: str
    mode: str
    runId: str | None = Field(default=None, validation_alias="run_id")
    proposedMemoryUpdates: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="proposed_memory_updates",
    )

    model_config = {
        "populate_by_name": True,
    }


class HealthComponent(BaseModel):
    status: str
    detail: str | None = None


class HealthStatus(BaseModel):
    overall: str
    mysql: HealthComponent
    redis: HealthComponent
    minio: HealthComponent
    vector: HealthComponent
    llm: HealthComponent


class BusinessRiskReadinessComponent(BaseModel):
    status: str
    detail: str | None = None


class BusinessRiskSourceReadinessStatus(BaseModel):
    overall: str
    route: BusinessRiskReadinessComponent
    config: BusinessRiskReadinessComponent
    persistence: BusinessRiskReadinessComponent
    llm: BusinessRiskReadinessComponent


class BusinessRiskResult(BaseModel):
    taskId: str
    status: TaskStatus
    runId: str = Field(validation_alias="run_id")
    riskSummary: str | None = None
    details: List[str] = Field(default_factory=list)
    proposedMemoryUpdates: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="proposed_memory_updates",
    )
    traceId: str | None = None
