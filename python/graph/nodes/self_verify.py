"""自验证节点 —— 对业务风险分析结果进行最终验证和整理。

本模块是业务风险分析流水线的"收尾"节点，负责：
1. 将不变量违反和方法问题整理为统一的风险项列表
2. 关联 RAG 检索到的历史事故（作为参考证据）
3. 生成最终的验证结果（verified_risks）

类比：
  就像法官在庭审结束前的"最终确认"——
  把所有证据（违反、问题）整理成清单，附上相关判例（历史事故），
  最终形成判决书。
"""
from __future__ import annotations

from graph.state import GraphState, NodeContext


def verify_business_risks(state: GraphState, ctx: NodeContext) -> GraphState:
    """验证并整理业务风险分析结果。

    从共享状态中读取各节点的产出，整理为统一的验证结果：
    - 不变量违反 → severity: high
    - 方法问题 → severity: medium
    - RAG 历史事故 → 作为关联证据附上

    参数:
        state: 共享状态，包含 business_risk_report、invariant_violations、
               method_issues、rag_context
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 verified_risks 字段
    """
    report = state.get("business_risk_report", {})
    violations = state.get("invariant_violations", {})
    method_issues = state.get("method_issues", {})
    rag_context = state.get("rag_context", [])

    # 整理风险项列表
    items = []
    # 不变量违反 → 高严重度（业务规则被破坏是最严重的）
    for violation in violations.get("violations", []) if isinstance(violations, dict) else []:
        items.append(
            {
                "type": "invariant_violation",    # 类型：不变量违反
                "severity": "high",
                "evidence": violation,
            }
        )
    # 方法问题 → 中严重度（热点方法需要关注）
    for issue in method_issues.get("issues", []) if isinstance(method_issues, dict) else []:
        items.append(
            {
                "type": "hotspot",                 # 类型：热点方法
                "severity": "medium",
                "evidence": issue,
            }
        )

    # 关联历史事故（RAG 检索到的，作为参考证据）
    related_incidents = []
    for entry in (rag_context if isinstance(rag_context, list) else []):
        if entry.get("score", 0) > 0:
            related_incidents.append({
                "title": entry.get("title", "unknown"),
                "snippet": entry.get("snippet", ""),
                "score": entry.get("score", 0),
                "source": entry.get("source", "unknown"),
            })

    # 将验证结果写入共享状态
    state["verified_risks"] = {
        "items": items,                                                    # 风险项列表
        "source_report_level": report.get("level", "LOW") if isinstance(report, dict) else "LOW",  # 原始报告等级
        "need_human_review": report.get("need_human_review", False) if isinstance(report, dict) else False,  # 是否需要人工审查
        "related_incidents": related_incidents[:5],                        # 关联历史事故（最多 5 个）
        "status": "READY",
    }
    return state
