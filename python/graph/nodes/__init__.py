# 节点导出 —— 按领域分组的 LangGraph 节点函数
#
# 集中导出所有节点函数，方便其他模块统一导入。
# 所有节点函数遵循统一签名：def node_fn(state, ctx) -> state
# (state: GraphState, ctx: NodeContext 输入，返回更新后的 GraphState)

from .classifier import classify_changes
from .deduplicate import deduplicate_findings
from .diff import analyze_diff
from .impact import analyze_impact
from .performance import analyze_performance
from .rag import run_rag
from .report import summarize
from .rules import run_rule_checks
from .scoring import score_risks
from .security import audit_security
from .triviality_check import check_triviality

__all__ = [
    "analyze_diff",
    "analyze_impact",
    "analyze_performance",
    "audit_security",
    "check_triviality",
    "classify_changes",
    "deduplicate_findings",
    "run_rag",
    "run_rule_checks",
    "score_risks",
    "summarize",
]
