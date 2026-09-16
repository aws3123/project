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

    title: str  # 建议标题
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
