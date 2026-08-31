"""深度阅读节点 —— 从源码包中提取热点方法的详细信息。

本模块负责从源码包中提取"热点"（hotspot）方法的详细信息：
- 热点：Java 端 AST 预筛出的可疑代码片段（可能包含业务风险的方法）
- 提取内容：文件路径、热点原因、代码片段、起止行号

类比：
  就像老师批改作文时"标记重点段落"——
  Java 端已经标记了哪些段落可疑，这里把详细内容提取出来供后续分析。
"""
from __future__ import annotations

from graph.state import GraphState, NodeContext


def deep_read_methods(state: GraphState, ctx: NodeContext) -> GraphState:
    """深度阅读热点方法，提取详细信息。

    扫描源码包中每个文件的热点列表，提取每个热点的详细信息
    （路径、原因、代码片段、行号范围），供后续节点分析和展示。

    参数:
        state: 共享状态，包含 source_package
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 method_issues 字段
    """
    source_package = state.get("source_package", {}) if isinstance(state.get("source_package", {}), dict) else {}
    files = source_package.get("files", []) if isinstance(source_package, dict) else []

    issues = []          # 提取的热点问题列表
    scanned_files = []   # 扫描过的文件路径列表
    for source_file in files:
        if not isinstance(source_file, dict):
            continue
        path = source_file.get("path", "")
        scanned_files.append(path)
        hotspots = source_file.get("hotspots", []) or []
        for hotspot in hotspots:
            if not isinstance(hotspot, dict):
                continue
            issues.append(
                {
                    "path": path,                                                    # 文件路径
                    "reason": hotspot.get("reason", "unknown hotspot"),              # 热点原因（为什么被标记）
                    "snippet": hotspot.get("snippet") or hotspot.get("raw_snippet") or "",  # 代码片段
                    "start_line": hotspot.get("start_line") or (hotspot.get("line_map") or {}).get("start_line"),  # 起始行号
                    "end_line": hotspot.get("end_line") or (hotspot.get("line_map") or {}).get("end_line"),        # 结束行号
                }
            )

    # 将方法问题列表写入共享状态
    state["method_issues"] = {
        "issues": issues,              # 热点问题列表
        "scanned_files": scanned_files, # 扫描的文件列表
        "status": "READY",
    }
    return state
