"""
LLM 结构化输出模型
====================

作用：
    定义大语言模型（LLM）返回的结构化数据的格式。

为什么需要这些模型？
    LLM 返回的内容不是随意的文本，而是有固定结构的 JSON。
    比如"打分节点"要求 LLM 返回一个包含 risk_score、breakdown 等字段的结构。
    这些模型就是用来"校验"LLM 返回的数据是否符合预期的——
    如果 LLM 返回了不合法的格式（比如 risk_score 是 200），Pydantic 会立刻报错。

什么是"结构化输出"？
    就是让 LLM 按照我们指定的格式返回数据，而不是自由发挥写一段话。
    这通常通过 "function calling" 或 "JSON mode" 来实现。
"""

# BaseModel 是 Pydantic 的数据模型基类
# Field 用于给字段添加约束和描述
from pydantic import BaseModel, Field


# =============================================================================
# 打分输出模型 —— LLM 打分节点的输出格式
# =============================================================================
class BreakdownItem(BaseModel):
    """单个维度的评分明细。

    比如安全性维度：dimension="security", score=80, reason="发现 SQL 注入风险"
    """
    # 维度名称
    dimension: str
    # 评分（0~100）
    score: int = Field(ge=0, le=100)
    # 评分理由（LLM 解释为什么给这个分数）
    reason: str


class ScoringOutput(BaseModel):
    """LLM 打分节点的完整输出。

    这是"评分节点"要求 LLM 返回的数据结构，包含总分、各维度明细、是否需要人工复核等。
    """
    # 整体风险评分（0~100）
    risk_score: int = Field(ge=0, le=100)
    # 各维度的评分明细列表
    breakdown: list[BreakdownItem]
    # 是否需要人工复核（LLM 自己判断的）
    need_human_review: bool
    # 风险摘要（一段话概括主要风险）
    risk_summary: str


# =============================================================================
# RAG 分析输出模型 —— LLM 分析 RAG 检索结果的输出格式
# =============================================================================
class RecommendationItem(BaseModel):
    """一条改进建议。"""
    title: str   # 建议标题
    detail: str  # 建议详情


class RAGAnalysisOutput(BaseModel):
    """LLM 对 RAG 检索到的历史事故的分析结果。

    RAG 检索到相关的历史事故后，LLM 会分析这些事故和当前代码变更的关联。
    """
    # 相关的历史事故 ID 列表
    related_incidents: list[str] = Field(default_factory=list)
    # 风险关联分析（LLM 解释当前变更和历史事故的关系）
    risk_association: str
    # 建议的后续行动列表
    suggested_actions: list[str] = Field(default_factory=list)


# =============================================================================
# 报告输出模型 —— LLM 生成审查报告的输出格式
# =============================================================================
class ReportOutput(BaseModel):
    """LLM 生成的审查报告。

    这是"报告生成节点"要求 LLM 返回的数据结构。
    """
    # 报告摘要（一段话概括整体审查结论）
    summary: str
    # 详细发现列表（每条是一个具体的风险描述）
    details: list[str]
    # 改进建议列表
    recommendations: list[RecommendationItem]
    # 报告中引用的图片引用列表（比如事故截图的引用）
    image_references: list[str] = Field(default_factory=list)


# =============================================================================
# 业务风险不变量模型 —— LLM 提取和检查业务规则的输出格式
# =============================================================================
class BusinessInvariantOutput(BaseModel):
    """LLM 提取出的业务不变量（Invariant）。

    什么是"业务不变量"？
        就是在任何情况下都必须成立的业务规则。
        比如"订单金额不能为负数"就是一个不变量——不管什么情况，
        如果订单金额为负，那就是 bug。
    """
    # 不变量的唯一标识
    invariant_id: str
    # 不变量名称，比如 "订单金额非负"
    name: str
    # 不变量的详细描述
    description: str
    # 严重程度：low（低）、medium（中）、high（高）
    severity: str = "medium"


class InvariantCheckOutput(BaseModel):
    """LLM 对某个业务不变量的检查结果。

    给定一个不变量（如"订单金额非负"），LLM 会检查当前代码是否违反了这个规则。
    """
    # 被检查的不变量 ID
    invariant_id: str
    # 是否被违反（True = 违反了，False = 没有违反）
    violated: bool
    # 置信度（0~1），LLM 对自己判断的确信程度。
    # 比如 0.9 表示"我非常确定这里违反了规则"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # 证据列表（LLM 列出支持其判断的代码片段或逻辑推理）
    evidence: list[str] = Field(default_factory=list)


# =============================================================================
# 深度阅读输出模型 —— LLM 深入分析某个方法的输出格式
# =============================================================================
class DeepReadOutput(BaseModel):
    """LLM 对某个方法进行"深度阅读"后的分析结果。

    "深度阅读"是指 LLM 仔细阅读一个方法的完整代码，找出潜在的问题。
    """
    # 被分析的方法名
    method_name: str
    # 发现的问题类型，比如 "SQL_INJECTION"、"NULL_POINTER"
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
# 业务风险汇总输出模型 —— LLM 对业务风险的整体评估
# =============================================================================
class BusinessRiskAggregateOutput(BaseModel):
    """LLM 对业务风险的整体汇总评估。

    这是"业务风险评估节点"要求 LLM 返回的最终结构。
    """
    # 整体风险级别：low / medium / high
    overall_risk_level: str = "medium"
    # 执行摘要（给管理层看的一段话概括）
    executive_summary: str
    # 提取出的业务不变量列表
    invariants: list[BusinessInvariantOutput] = Field(default_factory=list)
    # 不变量检查结果列表
    invariant_checks: list[InvariantCheckOutput] = Field(default_factory=list)
    # 深度阅读发现的问题列表
    deep_read_findings: list[DeepReadOutput] = Field(default_factory=list)


# =============================================================================
# 自验证输出模型 —— LLM 自检结果的输出格式
# =============================================================================
class SelfVerifyOutput(BaseModel):
    """LLM 自验证节点的输出。

    什么是"自验证"？
        就是让 LLM 回顾自己之前的分析结果，检查是否有遗漏或错误。
        类似于"做完题后检查一遍"。
    """
    # 是否通过验证（True = 之前的分析没问题，False = 发现了问题需要修正）
    passed: bool
    # 置信度（0~1），LLM 对自己自检结果的确信程度
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # 备注列表（LLM 补充的说明，比如"虽然通过了，但建议关注 XX 点"）
    notes: list[str] = Field(default_factory=list)
"""Pydantic schemas for LLM structured output validation."""

from pydantic import BaseModel, Field


class BreakdownItem(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=100)
    reason: str


class ScoringOutput(BaseModel):
    risk_score: int = Field(ge=0, le=100)
    breakdown: list[BreakdownItem]
    need_human_review: bool
    risk_summary: str


class RecommendationItem(BaseModel):
    title: str
    detail: str


class RAGAnalysisOutput(BaseModel):
    related_incidents: list[str] = Field(default_factory=list)
    risk_association: str
    suggested_actions: list[str] = Field(default_factory=list)


class ReportOutput(BaseModel):
    summary: str
    details: list[str]
    recommendations: list[RecommendationItem]
    image_references: list[str] = Field(default_factory=list)


class BusinessInvariantOutput(BaseModel):
    invariant_id: str
    name: str
    description: str
    severity: str = "medium"


class InvariantCheckOutput(BaseModel):
    invariant_id: str
    violated: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class DeepReadOutput(BaseModel):
    method_name: str
    issue_type: str
    risk_level: str = "medium"
    detail: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class BusinessRiskAggregateOutput(BaseModel):
    overall_risk_level: str = "medium"
    executive_summary: str
    invariants: list[BusinessInvariantOutput] = Field(default_factory=list)
    invariant_checks: list[InvariantCheckOutput] = Field(default_factory=list)
    deep_read_findings: list[DeepReadOutput] = Field(default_factory=list)


class SelfVerifyOutput(BaseModel):
    passed: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)
