"""
schemas 包初始化文件
======================

按分层拆分：
- schemas/api/    对外契约（request / result / backend_contract）
- schemas/domain/ 领域模型（enums / task / log / llm_output / semantic_finding / business_risk*）

调用方应直接按模块导入（如 `from schemas.api.request import ReviewRequest`）。
本文件仅为兼容保留，新代码无需经包级再导出。
"""

# --- 枚举类型 ---
from schemas.domain.enums import HandoffDecision, RAGStatus, ReviewMode, TaskStatus, Tier

# --- 业务风险分析相关模型 ---
from schemas.domain.business_risk import (
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
from schemas.domain.log import NodeLog     # 节点执行日志

# --- 请求模型 ---
from schemas.api.request import HandoffRequest, ReviewRequest

# --- 结果模型 ---
from schemas.api.result import BusinessRiskResult, ReviewResult, RiskBreakdown

# --- 任务模型 ---
from schemas.domain.task import ReviewTask

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