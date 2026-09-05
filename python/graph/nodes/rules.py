"""规则检查节点 —— 用预定义规则扫描代码变更。

本模块负责运行一组确定性规则工具（SQL 风险检查、API 破坏性检查、配置变更检查），
这些工具不需要 LLM，纯粹基于模式匹配/静态分析来发现问题。

类比：
  就像工厂里的"质检关卡"——用固定的检测标准（模板）逐个检查产品，
  不符合标准的就标记出来。不需要"专家判断"，规则说了算。
"""

from __future__ import annotations

from graph.state import GraphState, NodeContext
from tools.base import ToolContext, ToolResult

# 规则工具列表 —— 每个工具名对应 tools/ 目录下的一个检查器
RULE_TOOLS = [
    "sql_risk_checker",  # SQL 风险检查：检测危险的 SQL 操作
    "api_breaking_checker",  # API 破坏性检查：检测接口兼容性破坏
    "config_change_checker",  # 配置变更检查：检测可能出问题的配置改动
]

# 默认发现模板 —— 当工具没有发现任何问题时，用这个"占位"结果
# 为什么需要占位？避免前端处理空列表，统一数据格式
DEFAULT_FINDING = {
    "severity": "INFO",  # 严重级别：INFO（最低，仅通知）
    "category": "general",  # 分类：通用
    "title": "No findings",  # 标题：无发现
    "detail": "No rule findings",  # 详情
    "file": None,  # 不涉及具体文件
    "line": None,  # 不涉及具体行号
    "evidence": "",  # 无证据
    "suggestion": "No action required",  # 无需操作
    "confidence": 1.0,  # 置信度 100%（确定没问题）
}


def _normalize_finding(item: dict, tool: str) -> dict:
    """将单个发现标准化为统一格式。

    不同工具返回的发现格式可能略有差异，这个函数确保所有发现都有完整的字段。
    缺失的字段用 DEFAULT_FINDING 中的默认值填充。

    参数:
        item: 工具返回的原始发现字典
        tool: 产生该发现的工具名称（用于溯源）

    返回:
        标准化的发现字典，包含所有必需字段
    """
    return {
        "severity": item.get("severity", DEFAULT_FINDING["severity"]),
        "category": item.get(
            "category", tool.replace("_checker", "").replace("_tool", "")
        ),
        "title": item.get("title", DEFAULT_FINDING["title"]),
        "detail": item.get("detail", DEFAULT_FINDING["detail"]),
        "file": item.get("file"),
        "line": item.get("line"),
        "evidence": item.get("evidence", DEFAULT_FINDING["evidence"]),
        "suggestion": item.get("suggestion", DEFAULT_FINDING["suggestion"]),
        "confidence": item.get("confidence", DEFAULT_FINDING["confidence"]),
        "tool": tool,  # 记录来源工具，方便溯源
    }


def run_rule_checks(state: GraphState, ctx: NodeContext) -> GraphState:
    """执行所有规则检查工具，收集发现。

    依次运行 RULE_TOOLS 中的每个工具，将结果合并后写入 state["rule_findings"]。

    参数:
        state: 共享状态，包含 diff_analysis（由 analyze_diff 节点产出）
        ctx:   节点上下文（工具箱），通过 registry 调用工具

    返回:
        更新后的 state，新增了 rule_findings 字段
    """
    findings: list[dict] = []
    # 从 diff 分析结果中获取检查载荷
    payload = state.get("diff_analysis", {})
    context = ToolContext(task_id=ctx.task_id)
    # 依次运行每个规则工具
    for tool in RULE_TOOLS:
        result: ToolResult = ctx.registry.run(tool, payload, context)
        # 获取工具返回的发现列表；如果没有发现，用默认占位
        tool_findings = result.payload.get("findings", []) or [DEFAULT_FINDING]
        for item in tool_findings:
            findings.append(_normalize_finding(item, tool))
        # 记录工具调用日志（方便溯源和调试）
        state.setdefault("tool_logs", []).append(
            {
                "node": "rules",
                "tool": tool,
                "findings_count": len(tool_findings),
                "status": "success",
            }
        )
    # 将所有规则发现写入共享状态
    state["rule_findings"] = findings
    return state
