"""
schemas 包初始化文件
======================

作用：
    把所有常用的数据模型集中暴露到包级别，方便外部直接导入。

使用方式：
    不用写：from schemas.request import ReviewRequest
    可以写：from schemas import ReviewRequest

    不用写：from schemas.enums import TaskStatus
    可以写：from schemas import TaskStatus

__all__ 的作用：
    定义 "from schemas import *" 时会导入哪些名字。
    同时也是一种"公开 API 声明"——只有列在 __all__ 中的才是对外暴露的。
"""

# --- 枚举类型 ---
from .enums import HandoffDecision, RAGStatus, ReviewMode, TaskStatus, Tier

# --- 业务风险分析相关模型 ---
from .business_risk import (
    BusinessInvariant,       # 业务不变量定义
    BusinessRiskItem,        # 业务风险条目
    BusinessRiskReport,      # 业务风险报告
    BusinessRiskRequest,     # 业务风险请求
    BusinessRiskResponse,    # 业务风险响应
    DataFlowPath,            # 数据流路径
    InvariantViolation,      # 不变量违反
    MethodIssue,             # 方法问题
)

# --- 日志模型 ---
from .log import NodeLog     # 节点执行日志

# --- 请求模型 ---
from .request import HandoffRequest, ReviewRequest

# --- 结果模型 ---
from .result import BusinessRiskResult, ReviewResult, RiskBreakdown

# --- 任务模型 ---
from .task import ReviewTask

# 公开 API 声明：只有列在这里的名字才能通过 "from schemas import *" 导入
__all__ = [
    # 枚举
    "ReviewMode",
    "TaskStatus",
    "Tier",
    "RAGStatus",
    "HandoffDecision",
    # 请求
    "ReviewRequest",
    "HandoffRequest",
    # 结果
    "ReviewResult",
    "BusinessRiskResult",
    "RiskBreakdown",
    # 任务
    "ReviewTask",
    # 日志
    "NodeLog",
    # 业务风险
    "BusinessInvariant",
    "DataFlowPath",
    "InvariantViolation",
    "MethodIssue",
    "BusinessRiskItem",
    "BusinessRiskReport",
    "BusinessRiskRequest",
    "BusinessRiskResponse",
]
"""Public exports for schema consumers."""

from .enums import HandoffDecision, RAGStatus, ReviewMode, TaskStatus, Tier
from .business_risk import (
    BusinessInvariant,
    BusinessRiskItem,
    BusinessRiskReport,
    BusinessRiskRequest,
    BusinessRiskResponse,
    DataFlowPath,
    InvariantViolation,
    MethodIssue,
)
from .log import NodeLog
from .request import HandoffRequest, ReviewRequest
from .result import BusinessRiskResult, ReviewResult, RiskBreakdown
from .task import ReviewTask

__all__ = [
    "ReviewMode",
    "TaskStatus",
    "Tier",
    "RAGStatus",
    "HandoffDecision",
    "ReviewRequest",
    "HandoffRequest",
    "ReviewResult",
    "BusinessRiskResult",
    "RiskBreakdown",
    "ReviewTask",
    "NodeLog",
    "BusinessInvariant",
    "DataFlowPath",
    "InvariantViolation",
    "MethodIssue",
    "BusinessRiskItem",
    "BusinessRiskReport",
    "BusinessRiskRequest",
    "BusinessRiskResponse",
]
