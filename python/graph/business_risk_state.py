"""
业务风险审查的图状态定义
======================

本模块定义了业务风险审查流水线的共享状态结构。

与主审查流水线（GraphState）的关系：
  - 主流水线审查"代码质量风险"（安全漏洞、性能问题、规则违规）
  - 业务风险流水线审查"业务逻辑风险"（事务一致性、状态变更、并发竞态）
  - 两者共用类似的 TypedDict 模式，但字段不同

字段说明：
  - task_id / run_id / trace_id：任务追踪标识
  - request：原始审查请求
  - source_package：Java BFF 层预处理的源代码包（含方法骨架、热点标注）
  - business_invariants：业务不变量（如"库存扣减必须在事务内"）
  - data_flow_paths：数据流路径（方法间的调用链路）
  - invariant_violations：不变量违反项
  - method_issues：热点方法的问题
  - semantic_findings：LLM 语义分析发现
  - business_risk_report：最终的业务风险评估报告
  - verified_risks：经过自验证的风险项
"""
from __future__ import annotations

from typing import Any, TypedDict


class BusinessRiskGraphState(TypedDict, total=False):
    """业务风险审查流水线的共享状态字典。

    类比：和主审查的 GraphState 类似，也是一块"公共白板"，
    但上面写的是业务风险相关的内容（事务、并发、状态变更），而非代码质量问题。
    """
    task_id: str                          # 任务 ID
    run_id: str                           # 运行 ID（同一次审查可能有多个 run）
    trace_id: str | None                  # 链路追踪 ID（跨服务追踪用）
    request: dict[str, Any]               # 原始审查请求
    source_package: dict[str, Any]        # Java BFF 预处理的源代码包
    business_invariants: dict[str, Any]   # 业务不变量（提取结果）
    data_flow_paths: dict[str, Any]       # 数据流路径（调用链路）
    invariant_violations: dict[str, Any]  # 不变量违反项
    method_issues: dict[str, Any]         # 热点方法问题
    semantic_findings: dict[str, Any]     # LLM 语义分析发现
    business_risk_report: dict[str, Any]  # 业务风险评估报告
    verified_risks: dict[str, Any]        # 经过自验证的风险项
