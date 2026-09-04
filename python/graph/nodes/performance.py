"""性能分析节点 —— 薄适配器，领域逻辑在 domain/reviewers/performance_review。

只负责：从 state 读输入、调用领域纯函数、降级处理、写回 state/tool_logs。
"""
from __future__ import annotations

from domain.reviewers._findings import merge_findings, parse_llm_response
from domain.reviewers.performance_review import build_audit_messages, scan_deterministic
from domain.shared.diff_extractor import build_diff_snippet
from graph.state import GraphState, NodeContext


def analyze_performance(state: GraphState, ctx: NodeContext) -> GraphState:
    """性能审计主函数 —— 结合确定性扫描和 LLM 审计。

    （签名与语义不变，保证流水线与测试零改动。）
    """
    # ── 第一步：确定性扫描前置（保证降级安全）──────────────────────
    files = state.get("diff_analysis", {}).get("files", [])
    det_findings = scan_deterministic(files)
    state["performance_findings"] = det_findings  # 先落盘，后续 LLM 成功会覆盖

    # 没有 LLM 客户端 → 降级模式
    if ctx.llm_client is None:
        state.setdefault("tool_logs", []).append({
            "node": "performance",
            "method": "deterministic_only",
            "findings_count": len(det_findings),
            "status": "degraded",
        })
        return state

    # ── 第二步：提取代码片段，准备 LLM 审计 ────────────────────────
    impact_radius = state.get("impact_radius")
    code_graph = state.get("code_graph")
    diff_snippet, method_names = build_diff_snippet(
        files, max_files=5, max_chars_per_file=2500, max_chars_total=6000,
        impact_radius=impact_radius, code_graph=code_graph,
    )

    if not diff_snippet.strip():
        state.setdefault("tool_logs", []).append({
            "node": "performance",
            "method": "deterministic_only",
            "findings_count": len(det_findings),
            "status": "no_diff_for_llm",
        })
        return state

    # ── 第三步：LLM 审计（可选增强）────────────────────────────────
    messages = build_audit_messages(diff_snippet, method_names)
    llm_status = "success"
    llm_findings: list[dict] = []
    try:
        result = ctx.llm_client.chat(messages=messages, max_tokens=1024)
        llm_findings = parse_llm_response(result)
    except Exception:
        llm_findings = []  # LLM 失败时降级：保留确定性扫描结果
        llm_status = "llm_failed"

    # ── 第四步：合并去重 ────────────────────────────────────────────
    merged, llm_new_count = merge_findings(det_findings, llm_findings, category="performance")

    state["performance_findings"] = merged
    state.setdefault("tool_logs", []).append({
        "node": "performance",
        "method": "deterministic+llm",
        "det_findings_count": len(merged) - llm_new_count,
        "llm_findings_count": llm_new_count,
        "llm_status": llm_status,
        "status": "success",
    })
    return state