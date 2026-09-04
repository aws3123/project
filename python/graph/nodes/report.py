"""报告生成节点 —— 薄适配器，报告逻辑在 domain/reviewers/report_review。

只负责：读取 state、调用领域纯函数、异常降级、写回 state。
"""

from __future__ import annotations

from domain.reviewers.report_review import build_report_messages, template_fallback
from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError
from schemas.domain.llm_output import ReportOutput


def summarize(state: GraphState, ctx: NodeContext) -> GraphState:
    """报告生成主函数 —— 生成审查报告摘要和建议。

    （签名与语义不变，保证流水线与测试零改动。）
    """
    # 平凡变更 → 直接返回预填充结果（triviality_check 已设置）
    if state.get("trivial"):
        return state

    # 降级模式：没有 LLM 时用模板拼接
    if ctx.llm_client is None:
        _apply_template(state)
        return state

    # 准备风险评分数据（0-1 → 0-100）
    risk_score = state.get("risk_score", 0.5)
    if 0 <= risk_score <= 1:
        risk_score_value = int(round(risk_score * 100))
    else:
        risk_score_value = int(round(risk_score))

    breakdown = state.get("breakdown", [])
    rule_findings = state.get("rule_findings", [])
    rag_analysis = state.get("rag_analysis", "")
    risk_summary = state.get("risk_summary", "")
    rag_context = state.get("rag_context", [])

    messages = build_report_messages(
        risk_score_value,
        risk_summary,
        breakdown,
        rule_findings,
        rag_analysis,
        rag_context,
    )

    try:
        result = ctx.llm_client.chat_structured(
            messages=messages,
            output_schema=ReportOutput,
            max_tokens=1536,
        )
        state["summary"] = result.get("summary", "")
        state["details"] = result.get("details", [])
        state["recommendations"] = result.get("recommendations", [])
    except LLMStructuredOutputError:
        # LLM 输出格式错误 → 降级到模板模式
        _apply_template(state)

    return state


def _apply_template(state: GraphState) -> None:
    """应用模板降级报告到 state（纯副作用封装）。"""
    risk_score = state.get("risk_score") or 0.5
    layers = state.get("classification", {}).get("layers", [])
    rule_findings = state.get("rule_findings", [])
    coverage = state.get("classification", {}).get("summary", {}).get("coverage", 1)
    report = template_fallback(risk_score, layers, rule_findings, coverage)
    state["summary"] = report["summary"]
    state["details"] = report["details"]
    state["recommendations"] = report["recommendations"]
