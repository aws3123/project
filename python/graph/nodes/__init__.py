"""
节点导出 —— 按领域分组的 LangGraph 节点函数
================================================

作用：
    集中导出所有节点函数，方便其他模块统一导入。
    比如 from graph.nodes import analyze_diff, run_rag

节点函数的签名：
    所有节点函数都遵循相同的签名：
    def node_fn(state: GraphState, ctx: NodeContext) -> GraphState
    - state: 当前图状态（输入）
    - ctx: 节点上下文（包含工具注册表、LLM 客户端等）
    - 返回: 更新后的图状态
"""

# 导入所有节点函数
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

# __all__ 定义 from graph.nodes import * 时导出的符号列表
__all__ = [
    "analyze_diff",           # diff 分析
    "classify_changes",       # 变更分类
    "analyze_impact",         # 影响分析
    "run_rule_checks",        # 规则检查
    "run_rag",                # RAG 检索
    "audit_security",         # 安全审计
    "analyze_performance",    # 性能分析
    "extract_business_invariants",  # 业务不变量提取
    "trace_data_flow",        # 数据流追踪
    "check_invariants",       # 不变量检查
    "deep_read_methods",      # 深度阅读方法
    "assess_business_risk",   # 业务风险评估
    "business_risk_rag",      # 业务风险 RAG
    "verify_business_risks",  # 业务风险自验证
    "scan_semantic_hotspots", # 语义热点扫描
    "score_risks",            # 风险评分
    "summarize",              # 生成摘要
]
"""LangGraph node exports grouped by domain."""

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
