"""业务风险结果构建模块 —— 将流水线状态"翻译"成前端可消费的报告。

本模块负责将 BusinessRiskGraphState（流水线各节点写入的共享状态）
转换为 BusinessRiskReviewResult（前端可以直接使用的结构化结果）。

类比：
  如果流水线是"厨房做菜"，那这个模块就是"摆盘上桌"——
  把散落在各处的食材（状态字段）整理成一盘完整的菜（报告）。
"""
from __future__ import annotations

from schemas.domain.business_risk_review import (
    BusinessRiskReviewRequest,
    BusinessRiskReviewResult,
)
from graph.business_risk_state import BusinessRiskGraphState


def build_business_risk_result(
    request: BusinessRiskReviewRequest,
    state: BusinessRiskGraphState,
) -> BusinessRiskReviewResult:
    """将流水线最终状态转换为业务风险审查结果。

    从 state 中提取各节点的产出（报告、验证结果、不变量违反、方法问题、语义发现），
    组装成一个结构化的 BusinessRiskReviewResult 返回给前端。

    参数:
        request: 原始请求（用于获取 run_id、task_id 等元信息）
        state:   流水线执行完毕后的最终状态（包含所有节点的输出）

    返回:
        BusinessRiskReviewResult: 前端可消费的完整业务风险报告
    """
    # 从共享状态中提取各节点的产出（如果节点未执行则给空字典）
    report = state.get("business_risk_report") or {}         # 业务风险报告（由 business_risk 节点生成）
    verified = state.get("verified_risks") or {}             # 自验证后的风险列表（由 self_verify 节点生成）
    invariant_violations = state.get("invariant_violations") or {}  # 不变量违反（由 invariant_checker 节点生成）
    method_issues = state.get("method_issues") or {}         # 方法级问题（由 business_extractor 节点生成）
    semantic_findings = state.get("semantic_findings") or {} # 语义热点发现（由 semantic_hotspot_scan 节点生成）

    # 确定整体风险等级（LOW/MEDIUM/HIGH）
    level = str(report.get("level", "LOW")).lower()
    # 判断审查状态：如果报告或验证结果标记了"需要人工审查"，则状态为 human_review
    status = "completed"
    if report.get("need_human_review") or verified.get("need_human_review"):
        status = "human_review"

    # 生成执行摘要（一句话概括审查结论）
    executive_summary = report.get("summary") or "Business risk analysis completed"
    # 组装报告主体内容
    report_payload = {
        "overall_risk_level": level,                                    # 整体风险等级
        "executive_summary": executive_summary,                         # 执行摘要
        "invariant_violations": invariant_violations.get("violations", []),  # 不变量违反列表
        "method_issues": method_issues.get("issues", []),               # 方法级问题列表
        "semantic_findings": semantic_findings.get("items", []),        # 语义发现列表
        "semantic_status": semantic_findings.get("status"),             # 语义分析状态（READY/disabled/llm_failed）
        "items": verified.get("items", []),                             # 验证后的风险项
        "related_incidents": verified.get("related_incidents", []),     # 关联的历史事故（来自 RAG）
    }

    # 提议的记忆更新（用于后续更新业务知识库的统计信息）
    proposed_memory_updates = {
        "business_risk_level": level,                                    # 当前风险等级
        "violation_count": len(invariant_violations.get("violations", [])),  # 不变量违反数量
        "method_issue_count": len(method_issues.get("issues", [])),     # 方法问题数量
        "semantic_count": len(semantic_findings.get("items", [])),      # 语义发现数量
    }

    return BusinessRiskReviewResult(
        run_id=state.get("run_id", request.run_id),         # 运行 ID（优先用状态中的，兜底用请求中的）
        task_id=state.get("task_id", request.task_id),      # 任务 ID
        status=status,                                       # 审查状态（completed/human_review）
        report=report_payload,                               # 报告主体
        proposed_memory_updates=proposed_memory_updates,     # 提议的记忆更新
        trace_id=state.get("trace_id", request.trace_id),   # 链路追踪 ID
    )
