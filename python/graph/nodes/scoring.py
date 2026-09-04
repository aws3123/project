"""风险评分节点 —— 薄适配器，评分逻辑在 domain/reviewers/scoring_review。

只负责：读取 state、调用领域纯函数、异常降级、写回 state/字段。
"""
from __future__ import annotations

from domain.reviewers.scoring_review import (
    build_cross_text,
    build_findings_text,
    build_impact_text,
    build_scoring_messages,
    compute_deterministic,
    cross_validate,
    parse_scoring_result,
)
from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError
from schemas.llm_output import ScoringOutput


def score_risks(state: GraphState, ctx: NodeContext) -> GraphState:
    """风险评分主函数 —— 综合所有分析结果计算风险分数。

    （签名与语义不变，保证流水线与测试零改动。）
    """
    # 平凡变更 → 直接返回预填充结果（triviality_check 已设置）
    if state.get("trivial"):
        return state

    # 读取去重节点的预计算结果（deduplicate 已运行时）
    cross_merged = state.get("cross_validated_findings", [])
    force_human = state.get("force_human_review", False)
    # 向后兼容：deduplicate 未运行时现场计算
    if "cross_validated_findings" not in state:
        sources = {
            "rules": state.get("rule_findings", []),
            "security": state.get("security_findings", []),
            "performance": state.get("performance_findings", []),
        }
        cross_merged, force_human = cross_validate(sources)

    # 降级模式：没有 LLM 时用确定性公式评分
    if ctx.llm_client is None:
        _apply_deterministic(state, force_human)
        return state

    # ── LLM 结构化评分 ──────────────────────────────────────────────
    rule_findings = state.get("rule_findings", [])
    security_findings = state.get("security_findings", [])
    performance_findings = state.get("performance_findings", [])
    rag_analysis = state.get("rag_analysis", "")
    classification = state.get("classification", {})
    coverage = classification.get("summary", {}).get("coverage", 1.0)
    impact_radius = state.get("impact_radius", {})

    findings_text = build_findings_text(rule_findings, security_findings, performance_findings)
    cross_text = build_cross_text(cross_merged, force_human)
    impact_text = build_impact_text(impact_radius)
    messages = build_scoring_messages(findings_text, cross_text, impact_text, rag_analysis, coverage)

    try:
        result = ctx.llm_client.chat_structured(
            messages=messages, output_schema=ScoringOutput, max_tokens=1024,
        )
        parsed = parse_scoring_result(result, force_human)
        state["risk_score"] = parsed["risk_score"]
        state["breakdown"] = parsed["breakdown"]
        state["need_human_review"] = parsed["need_human_review"]
        state["risk_summary"] = parsed["risk_summary"]
    except LLMStructuredOutputError:
        # LLM 输出格式错误 → 降级到确定性评分
        _apply_deterministic(state, force_human)

    return state


def _apply_deterministic(state: GraphState, force_human: bool) -> None:
    """应用确定性评分到 state 上的纯副作用封装。"""
    rule_findings = state.get("rule_findings", [])
    security_findings = state.get("security_findings", [])
    performance_findings = state.get("performance_findings", [])
    rag_context = state.get("rag_context", [])
    impact_radius = state.get("impact_radius", {})
    coverage = state.get("classification", {}).get("summary", {}).get("coverage", 1.0)

    outcome = compute_deterministic(
        rule_findings, security_findings, performance_findings,
        rag_context, impact_radius, coverage, force_human,
    )
    state["risk_score"] = outcome["risk_score"]
    state["breakdown"] = outcome["breakdown"]
    state["need_human_review"] = outcome["need_human_review"]