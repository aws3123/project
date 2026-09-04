"""业务风险评估节点 —— 综合所有业务风险分析结果，给出风险等级。

本模块负责综合以下节点的分析结果，评估整体业务风险等级：
- invariant_violations：不变量违反（来自 invariant_checker）
- method_issues：方法级问题（来自 deep_reader）
- data_flow_paths：数据流路径（来自 dataflow_tracer）
- semantic_findings：语义发现（来自 semantic_hotspot_scan）

风险等级判定：
  - HIGH：有不变量违反 或 有语义发现
  - MEDIUM：有方法问题 或 数据流路径 > 3 条
  - LOW：以上都没有

类比：
  就像医生综合各项检查结果下诊断——
  化验报告（不变量）、影像检查（语义分析）、体征监测（方法问题）
  都看完了，最后给出一个整体诊断。
"""

from __future__ import annotations

from graph.state import GraphState, NodeContext


def assess_business_risk(state: GraphState, ctx: NodeContext) -> GraphState:
    """综合评估业务风险等级。

    从共享状态中读取各业务风险分析节点的产出，根据规则判定整体风险等级，
    生成业务风险报告写入 state["business_risk_report"]。

    参数:
        state: 共享状态，包含所有前序业务风险分析节点的输出
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 business_risk_report 字段
    """
    # 读取各节点的产出
    violations = state.get("invariant_violations", {})
    method_issues = state.get("method_issues", {})
    data_flow_paths = state.get("data_flow_paths", {})
    semantic_findings = state.get("semantic_findings", {})

    # 统计各类问题的数量
    violation_count = (
        len(violations.get("violations", [])) if isinstance(violations, dict) else 0
    )
    issue_count = (
        len(method_issues.get("issues", [])) if isinstance(method_issues, dict) else 0
    )
    path_count = (
        len(data_flow_paths.get("paths", []))
        if isinstance(data_flow_paths, dict)
        else 0
    )
    semantic_count = (
        len(semantic_findings.get("items", []))
        if isinstance(semantic_findings, dict)
        else 0
    )

    # 根据规则判定风险等级
    if semantic_count > 0 or violation_count > 0:
        level = "HIGH"  # 有不变量违反或语义发现 → 高风险
    elif issue_count > 0 or path_count > 3:
        level = "MEDIUM"  # 有方法问题或数据流路径过多 → 中风险
    else:
        level = "LOW"  # 以上都没有 → 低风险

    # 生成摘要文本
    if violation_count > 0:
        summary = "Potential business risk detected in state-changing flow"
    elif semantic_count > 0:
        summary = "Semantic analysis detected potential business risk in hotspots"
    elif issue_count > 0:
        summary = "Business risk hotspots require review"
    else:
        summary = "Business risk analysis completed"

    # 将业务风险报告写入共享状态
    state["business_risk_report"] = {
        "level": level,  # 风险等级（HIGH/MEDIUM/LOW）
        "summary": summary,  # 摘要文本
        "violation_count": violation_count,  # 不变量违反数
        "semantic_count": semantic_count,  # 语义发现数
        "method_issue_count": issue_count,  # 方法问题数
        "path_count": path_count,  # 数据流路径数
        "need_human_review": level != "LOW",  # 非低风险 → 需要人工审查
        "status": "READY",
    }
    return state
