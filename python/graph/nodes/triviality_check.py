"""平凡变更检查节点 — 判断变更是否足够简单以跳过深度分析。

作用：
    在 classifier 之后、impact 之前执行。
    如果判定为平凡变更（纯注释/文档/配置，无风险关键词，行数 < 阈值）：
      1. 设置 state["trivial"] = True
      2. 预填充 risk_score / breakdown / summary / details / recommendations
      3. 后续节点（rag / 并行 Agent / scoring / report）检测到 trivial 标志后跳过 LLM 调用

为什么需要这个节点？
    完整流水线每次执行约 7-16 秒，包含 5-7 次 LLM 调用、~16500 tokens。
    但 30-40% 的 PR 是平凡变更（注释修改、文档更新、配置调整），
    这些 PR 不需要安全审计、性能分析或 RAG 检索。
    triviality_check 可以直接跳过这些重计算，节省成本。
"""

from __future__ import annotations

from domain.reviewers.triviality_review import is_trivial, prefilled_fields
from graph.state import GraphState, NodeContext


def check_triviality(state: GraphState, ctx: NodeContext) -> GraphState:
    """平凡变更检查节点的主函数。

    判定逻辑（全部满足才视为平凡）：
      1. diff 行数 < 20（新增+删除）
      2. 不含核心风险关键词（DELETE/DROP/password/secret 等）
      3. 满足以下之一：
         a. 所有变更文件都是文档/配置文件
         b. 所有新增行都是注释或空行

    如果判定为平凡，预填充所有结果字段，后续节点检测 trivial 标志后短路返回。
    """
    diff_analysis = state.get("diff_analysis", {})
    diff_summary = diff_analysis.get("summary", {})
    diff_size = diff_summary.get("added_lines", 0) + diff_summary.get(
        "deleted_lines", 0
    )

    # 延迟导入避免循环依赖
    from graph.agent_selector import CORE_RISK_KEYWORDS

    if is_trivial(diff_analysis, CORE_RISK_KEYWORDS):
        state["trivial"] = True
        layers = state.get("classification", {}).get("layers", [])
        state.update(prefilled_fields(layers=layers, diff_size=diff_size))
    else:
        state["trivial"] = False

    return state
