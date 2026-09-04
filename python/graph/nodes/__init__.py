# 节点导出 —— 按领域分组的 LangGraph 节点函数
#
# 集中导出所有节点函数，方便其他模块统一导入。
# 所有节点函数遵循统一签名：def node_fn(state, ctx) -> state
# (state: GraphState, ctx: NodeContext 输入，返回更新后的 GraphState)

from .diff import analyze_diff
from .classifier import classify_changes
from .impact import analyze_impact
from .rules import run_rule_checks
from .rag import run_rag
from .security import audit_security
from .performance import analyze_performance
from .business_extractor import extract_business_invariants
from .dataflow_tracer import trace_data_flow
from .invariant_checker import check_invariants
from .deep_reader import deep_read_methods
from .business_risk import assess_business_risk
from .business_risk_rag import business_risk_rag
from .self_verify import verify_business_risks
from .semantic_hotspot_scan import scan_semantic_hotspots
from .scoring import score_risks
from .report import summarize
from .deduplicate import deduplicate_findings
from .triviality_check import check_triviality

__all__ = [
    "analyze_diff",
    "classify_changes",
    "analyze_impact",
    "run_rule_checks",
    "run_rag",
    "audit_security",
    "analyze_performance",
    "extract_business_invariants",
    "trace_data_flow",
    "check_invariants",
    "deep_read_methods",
    "assess_business_risk",
    "business_risk_rag",
    "verify_business_risks",
    "scan_semantic_hotspots",
    "score_risks",
    "summarize",
    "deduplicate_findings",
    "check_triviality",
]
