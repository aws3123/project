"""
业务风险分析模型
==================

作用：
    定义业务风险分析场景中的请求和响应数据结构。

什么是"业务风险分析"？
    和代码级审查（找 SQL 注入、空指针等）不同，业务风险分析关注的是更高层面的问题：
    - 业务规则是否被违反？（比如"退款金额不能超过订单金额"）
    - 数据流向是否安全？（比如"用户密码是否被传到了不该去的地方"）
    - 代码变更是否影响了关键业务流程？

核心概念：
    - 不变量（Invariant）：业务中必须始终成立的规则
    - 数据流路径（DataFlowPath）：数据从源头到终点的流转路径
    - 方法问题（MethodIssue）：某个方法中发现的具体问题
"""

# Any 表示任意类型
from typing import Any

# BaseModel 是 Pydantic 的数据模型基类
# Field 用于给字段添加约束
from pydantic import BaseModel, Field


# =============================================================================
# 业务不变量模型 —— 必须始终成立的规则
# =============================================================================
class BusinessInvariant(BaseModel):
    """业务不变量定义。

    不变量就是"在任何合法状态下都必须为真"的条件。
    比如：
      - "库存数量 >= 0"（库存不能为负）
      - "订单总金额 = 各商品金额之和"（金额必须对得上）
    """
    # 不变量的唯一标识，比如 "INV-001"
    invariant_id: str
    # 不变量名称，比如 "库存非负"
    name: str
    # 不变量的详细描述
    description: str
    # 严重程度：low / medium / high
    severity: str = "medium"
    # 标签列表，用于分类和检索，比如 ["finance", "order"]
    tags: list[str] = Field(default_factory=list)


# =============================================================================
# 数据流路径模型 —— 数据在代码中的流转路径
# =============================================================================
class DataFlowPath(BaseModel):
    """数据在代码中的流转路径。

    追踪数据从"源头"经过"中间环节"最终到达"终点"的完整路径。
    比如：用户输入 → Service 层 → DAO 层 → 数据库（如果中间没有做过滤，
    就可能是 SQL 注入风险）。
    """
    # 数据源头，比如 "HttpServletRequest.getParameter()"
    source: str
    # 中间经过的环节列表，比如 ["UserService.validate()", "OrderDAO.insert()"]
    through: list[str] = Field(default_factory=list)
    # 数据终点，比如 "database query"
    sink: str
    # 是否跨越了信任边界（比如从外部用户输入直接进入内部服务）
    # 跨越信任边界的数据流通常需要额外的安全检查
    trust_boundary_crossed: bool = False


# =============================================================================
# 不变量违反模型 —— 某个不变量是否被违反
# =============================================================================
class InvariantViolation(BaseModel):
    """对某个业务不变量的检查结果。"""
    # 被检查的不变量 ID
    invariant_id: str
    # 是否被违反（True = 代码违反了这个规则）
    violated: bool
    # 证据列表（支持判断的代码片段或推理过程）
    evidence: list[str] = Field(default_factory=list)
    # 置信度（0~1），对判断的确信程度
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# 方法问题模型 —— 某个方法中发现的具体问题
# =============================================================================
class MethodIssue(BaseModel):
    """在某个方法中发现的具体问题。"""
    # 方法名称
    method_name: str
    # 问题类型，比如 "SQL_INJECTION"、"MISSING_NULL_CHECK"
    issue_type: str
    # 风险级别：low / medium / high
    risk_level: str = "medium"
    # 问题的详细描述
    detail: str
    # 问题所在的文件路径
    file_path: str | None = None
    # 问题代码的起始行号
    line_start: int | None = None
    # 问题代码的结束行号
    line_end: int | None = None


# =============================================================================
# 业务风险条目模型 —— 一个具体的业务风险
# =============================================================================
class BusinessRiskItem(BaseModel):
    """一个具体的业务风险条目。

    每个条目描述了一个已识别的业务风险，包括它的严重程度、影响范围、
    违反的不变量、证据和缓解措施。
    """
    # 风险唯一标识
    risk_id: str
    # 风险标题，比如 "订单金额可能被篡改"
    title: str
    # 风险摘要
    summary: str
    # 严重程度：low / medium / high
    severity: str = "medium"
    # 风险类别，比如 "financial"、"data_integrity"
    category: str
    # 受影响的方法列表
    affected_methods: list[str] = Field(default_factory=list)
    # 违反的不变量列表
    invariant_violations: list[InvariantViolation] = Field(default_factory=list)
    # 支持这个风险判断的证据列表
    evidence: list[str] = Field(default_factory=list)
    # 缓解措施列表（建议怎么修复或降低风险）
    mitigations: list[str] = Field(default_factory=list)


# =============================================================================
# 业务风险报告模型 —— 完整的风险评估报告
# =============================================================================
class BusinessRiskReport(BaseModel):
    """业务风险评估的完整报告。

    汇总了所有不变量、数据流路径、方法问题和风险条目。
    """
    # 整体风险级别：low / medium / high
    overall_risk_level: str = "medium"
    # 执行摘要（给管理层看的概括性描述）
    executive_summary: str
    # 识别出的不变量列表
    invariants: list[BusinessInvariant] = Field(default_factory=list)
    # 识别出的数据流路径列表
    data_flow_paths: list[DataFlowPath] = Field(default_factory=list)
    # 发现的方法问题列表
    method_issues: list[MethodIssue] = Field(default_factory=list)
    # 业务风险条目列表
    items: list[BusinessRiskItem] = Field(default_factory=list)


# =============================================================================
# 业务风险请求模型 —— 发起业务风险分析的请求
# =============================================================================
class BusinessRiskRequest(BaseModel):
    """发起业务风险分析的请求数据。"""
    # 任务 ID（可选，异步场景下由系统分配）
    task_id: str | None = None
    # 项目标识
    project_id: str
    # 仓库地址
    repo: str
    # 分支名称
    branch: str
    # 要分析的文件列表，每个文件是 {"path": "...", "content": "..."} 的字典
    files: list[dict[str, str]] = Field(default_factory=list)
    # 会话 ID（用于多轮对话）
    session_id: str | None = None
    # 请求 ID
    request_id: str | None = None
    # 对话轮次
    dialog_turn: int | None = None
    # 记忆上下文
    memory_context: dict[str, Any] = Field(default_factory=dict)
    # 记忆版本号
    memory_version: str | None = None
    # 用户反馈信号
    user_feedback_signals: dict[str, Any] = Field(default_factory=dict)
    # 链路追踪 ID
    trace_id: str | None = None


# =============================================================================
# 业务风险响应模型 —— 业务风险分析的返回结果
# =============================================================================
class BusinessRiskResponse(BaseModel):
    """业务风险分析的响应数据。"""
    # 运行 ID，标识这次分析的运行实例
    run_id: str
    # 任务 ID
    task_id: str | None = None
    # 状态，默认 "completed"
    status: str = "completed"
    # 完整的风险评估报告
    report: BusinessRiskReport
    # 建议的记忆更新
    proposed_memory_updates: dict[str, Any] = Field(default_factory=dict)
    # 链路追踪 ID
    trace_id: str | None = None
"""Schemas for business-risk analysis requests and responses."""

from typing import Any

from pydantic import BaseModel, Field


class BusinessInvariant(BaseModel):
    invariant_id: str
    name: str
    description: str
    severity: str = "medium"
    tags: list[str] = Field(default_factory=list)


class DataFlowPath(BaseModel):
    source: str
    through: list[str] = Field(default_factory=list)
    sink: str
    trust_boundary_crossed: bool = False


class InvariantViolation(BaseModel):
    invariant_id: str
    violated: bool
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class MethodIssue(BaseModel):
    method_name: str
    issue_type: str
    risk_level: str = "medium"
    detail: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class BusinessRiskItem(BaseModel):
    risk_id: str
    title: str
    summary: str
    severity: str = "medium"
    category: str
    affected_methods: list[str] = Field(default_factory=list)
    invariant_violations: list[InvariantViolation] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list)


class BusinessRiskReport(BaseModel):
    overall_risk_level: str = "medium"
    executive_summary: str
    invariants: list[BusinessInvariant] = Field(default_factory=list)
    data_flow_paths: list[DataFlowPath] = Field(default_factory=list)
    method_issues: list[MethodIssue] = Field(default_factory=list)
    items: list[BusinessRiskItem] = Field(default_factory=list)


class BusinessRiskRequest(BaseModel):
    task_id: str | None = None
    project_id: str
    repo: str
    branch: str
    files: list[dict[str, str]] = Field(default_factory=list)
    session_id: str | None = None
    request_id: str | None = None
    dialog_turn: int | None = None
    memory_context: dict[str, Any] = Field(default_factory=dict)
    memory_version: str | None = None
    user_feedback_signals: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


class BusinessRiskResponse(BaseModel):
    run_id: str
    task_id: str | None = None
    status: str = "completed"
    report: BusinessRiskReport
    proposed_memory_updates: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
