"""代码差异分析节点 —— 流水线的"第一道工序"。

本模块负责分析代码变更（diff），提取出变更的文件、行号等元信息，
供后续节点（安全审计、性能分析等）使用。

类比：
  就像审稿前先"标记出哪些段落被修改了"——
  先搞清楚改了哪里，后面的专家才能有针对性地审查。
"""
from __future__ import annotations

from graph.state import GraphState, NodeContext
from tools.base import ToolContext, ToolResult


def analyze_diff(state: GraphState, ctx: NodeContext) -> GraphState:
    """分析代码差异，提取变更元信息。

    调用 diff_analyzer 工具，从请求中提取变更的文件列表和 diff URL，
    分析后将结果写入 state["diff_analysis"]，供后续节点使用。

    参数:
        state: 共享状态，包含 request（原始请求）
        ctx:   节点上下文（工具箱），包含工具注册表等

    返回:
        更新后的 state，新增了 diff_analysis 字段
    """
    # 从请求中提取文件列表和 diff URL
    files = state["request"].get("files", [])
    payload = {"files": files, "diffUrl": state["request"].get("diffUrl")}
    # 调用 diff_analyzer 工具执行分析
    result: ToolResult = ctx.registry.run("diff_analyzer", payload, ToolContext(task_id=ctx.task_id))
    # 将分析结果写入共享状态
    state["diff_analysis"] = result.payload
    return state
