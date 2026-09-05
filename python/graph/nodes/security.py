"""安全审计节点 —— 薄适配器，领域逻辑在 domain/reviewers/security_review。

本节点只负责：
- 从 state 读取输入（diff_analysis 的 files、impact_radius、code_graph）
- 调用领域纯函数（确定性扫描 + LLM 审计）
- 降级处理（无 LLM / 无 diff / LLM 失败）与 tool_logs 落盘
- 将结果写回 state
"""

from __future__ import annotations

from domain.reviewers._findings import merge_findings, parse_llm_response
from domain.reviewers.security_review import build_audit_messages, scan_deterministic
from domain.shared.diff_extractor import build_diff_snippet
from graph.state import GraphState, NodeContext


def audit_security(state: GraphState, ctx: NodeContext) -> GraphState:
    """安全审计主函数 —— 结合确定性扫描和 LLM 审计。

    （签名与语义不变，保证流水线与测试零改动。）
    """
    # ── 第一步：确定性扫描前置（保证降级安全）──────────────────────
    files = state.get("diff_analysis", {}).get("files", [])
    det_findings = scan_deterministic(files)
    state["security_findings"] = det_findings  # 先落盘，后续 LLM 成功会覆盖

    # 没有 LLM 客户端 → 降级模式，直接用确定性扫描结果
    if ctx.llm_client is None:
        state.setdefault("tool_logs", []).append(
            {
                "node": "security",
                "method": "deterministic_only",
                "findings_count": len(det_findings),
                "status": "degraded",
            }
        )
        return state

    # ── 第二步：提取代码片段，准备 LLM 审计 ────────────────────────
    impact_radius = state.get("impact_radius")
    code_graph = state.get("code_graph")
    diff_snippet, method_names = build_diff_snippet(
        files,
        max_files=5,
        max_chars_per_file=2500,
        max_chars_total=6000,
        impact_radius=impact_radius,
        code_graph=code_graph,
    )

    if not diff_snippet.strip():
        # 无 diff 内容，跳过 LLM，保留确定性扫描结果
        state.setdefault("tool_logs", []).append(
            {
                "node": "security",
                "method": "deterministic_only",
                "findings_count": len(det_findings),
                "status": "no_diff_for_llm",
            }
        )
        return state

    # ── 第三步：LLM 审计（可选增强；react=True 时进入自主取证模式）────
    react_mode = bool((state.get("request") or {}).get("react"))
    llm_status = "success"
    llm_findings: list[dict] = []

    if react_mode:
        from services.react_agent import ReActAgent

        system_prompt = (
            "你是安全审计专家。审阅变更代码，判断是否存在注入、XSS、硬编码密钥、"
            "越权/权限缺失等问题。可调用工具补充取证（如代码图谱、历史事故、AST）。"
            "最终必须输出合法 JSON："
            '{"findings":[{"severity":"HIGH/MEDIUM/LOW/INFO","title":"...","detail":"...",'
            '"file":"...","line":0,"evidence":"...","suggestion":"...","confidence":0.x}]}'
        )
        user_content = (
            f"代码片段：\n{diff_snippet}\n\n"
            f"变更分类：{state.get('classification')}\n"
            f"影响范围：{state.get('impact_radius')}"
        )
        agent = ReActAgent(
            ctx.llm_client,
            ctx.registry,
            ctx.task_id,
            allowed_tools=["code_knowledge_graph", "incident_search", "ast_parser"],
            node_name="security",
        )
        try:
            result, tool_trace = agent.run(system_prompt, user_content, max_tokens=1024)
            llm_findings = parse_llm_response(result)
            if tool_trace:
                state.setdefault("tool_logs", []).extend(tool_trace)
        except Exception:
            llm_findings = []  # 回退：保留确定性扫描结果
            llm_status = "react_failed"
    else:
        messages = build_audit_messages(diff_snippet, method_names)
        try:
            result = ctx.llm_client.chat(messages=messages, max_tokens=1024)
            llm_findings = parse_llm_response(result)
        except Exception:
            llm_findings = []  # LLM 失败时降级：保留确定性扫描结果
            llm_status = "llm_failed"

    # ── 第四步：合并去重 ────────────────────────────────────────────
    merged, llm_new_count = merge_findings(det_findings, llm_findings)

    # 更新最终结果（包含确定性 + LLM 补充）
    state["security_findings"] = merged
    state.setdefault("tool_logs", []).append(
        {
            "node": "security",
            "method": "deterministic+llm",
            "det_findings_count": len(merged) - llm_new_count,
            "llm_findings_count": llm_new_count,
            "llm_status": llm_status,
            "status": "success",
        }
    )
    return state
