"""
枚举定义模块
==============

作用：
    定义整个 schemas 模块中用到的所有"枚举类型"。

什么是枚举（Enum）？
    枚举就是把某个"只能取几个固定值"的变量，用一种规范的方式定义出来。
    比如"任务状态"只能是"排队中/处理中/成功/失败"这几种，不可能有别的值。
    用枚举可以防止你拼写错误（比如把 "SUCCEDED" 少写一个 E），
    因为 IDE 会自动补全，写错了也会立刻报错。

为什么继承 (str, Enum)？
    继承 str 意味着枚举值同时也是字符串，可以直接和 JSON 互转。
    比如 ReviewMode.SYNC 的值就是字符串 "SYNC"，不需要额外转换。
"""

# 从 Python 标准库导入 Enum 基类
from enum import Enum


# =============================================================================
# 审查模式枚举
# =============================================================================
# 审查请求的执行模式：
#   SYNC  → 同步模式：前端发请求后一直等着，直到审查完成才返回结果
#   ASYNC → 异步模式：前端发请求后立刻返回一个任务ID，之后通过轮询或 SSE 获取结果
class ReviewMode(str, Enum):
    """支持的审查执行模式。"""

    SYNC = "SYNC"
    ASYNC = "ASYNC"


# =============================================================================
# 任务状态枚举
# =============================================================================
# 一个审查任务从创建到结束，会经历以下状态（类似订单状态流转）：
#   QUEUED      → 已入队，等待处理（像餐厅里"等叫号"）
#   PROCESSING  → 正在处理中（像餐厅里"正在做菜"）
#   SUCCEEDED   → 成功完成
#   FAILED      → 处理失败（出错了）
#   NEED_REVIEW → 需要人工复核（AI 不确定，交给人类判断）
class TaskStatus(str, Enum):
    """审查任务的生命周期状态。"""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEED_REVIEW = "NEED_REVIEW"


# =============================================================================
# 审查层级枚举
# =============================================================================
# 代码审查分两个层级：
#   RULE_ONLY     → 仅基于规则审查（不调用 LLM，速度快但深度有限）
#   LLM_ENHANCED  → LLM 增强审查（调用大模型做深度分析，更准但更慢）
class Tier(str, Enum):
    RULE_ONLY = "RULE_ONLY"
    LLM_ENHANCED = "LLM_ENHANCED"


# =============================================================================
# RAG 检索状态枚举
# =============================================================================
# 追踪 RAG（检索增强生成）在一次运行中的健康状态：
#   NORMAL   → 检索正常，找到了足够的参考资料
#   DEGRADED → 检索降级，没找到什么有用的资料（可能影响审查质量）
class RAGStatus(str, Enum):
    """追踪 RAG 检索在一次运行中的健康状态。"""

    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"


# =============================================================================
# 审查决策枚举
# =============================================================================
# 人工审查后的决策结果：
#   APPROVED          → 通过（代码没问题，可以合并）
#   REJECTED          → 拒绝（代码有严重问题，不能合并）
#   CHANGES_REQUESTED → 需要修改（有问题但不至于拒绝，改改就行）
class HandoffDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


"""Enum definitions shared across schema modules."""

from enum import Enum


class ReviewMode(str, Enum):
    """Supported execution modes for a review request."""

    SYNC = "SYNC"
    ASYNC = "ASYNC"


class TaskStatus(str, Enum):
    """Possible lifecycle states for a review task."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEED_REVIEW = "NEED_REVIEW"


class Tier(str, Enum):
    RULE_ONLY = "RULE_ONLY"
    LLM_ENHANCED = "LLM_ENHANCED"


class RAGStatus(str, Enum):
    """Tracks the health of RAG retrieval during a run."""

    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"


class HandoffDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
