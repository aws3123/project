"""去重节点 — 交叉验证并行 Agent 的发现，合并重复项，检测矛盾。

薄适配器：领域逻辑用 domain/reviewers/_findings.cross_validate（与 scoring 共享）。
"""

from __future__ import annotations

from domain.reviewers._findings import cross_validate
from graph.state import GraphState, NodeContext


def deduplicate_findings(state: GraphState, ctx: NodeContext) -> GraphState:
    """去重节点的主函数 — 交叉验证并行 Agent 的发现。

    输入：state["rule_findings"], state["security_findings"], state["performance_findings"]
    输出：state["cross_validated_findings"]、state["force_human_review"]

    如果 state 已有预计算结果（如平凡变更场景），直接跳过。
    """
    # 平凡变更 → 跳过（triviality_check 已预填充）
    if state.get("trivial"):
        return state

    sources = {
        "rules": state.get("rule_findings", []),
        "security": state.get("security_findings", []),
        "performance": state.get("performance_findings", []),
    }
    merged, force_human = cross_validate(sources)
    state["cross_validated_findings"] = merged
    state["force_human_review"] = force_human
    return state
