"""数据流追踪节点 —— 追踪代码中数据的流动路径。

本模块负责从源码包中追踪"数据是怎么流动的"：
- 哪些文件是入口（entry files）
- 哪些方法调用了其他方法（调用链）
- 数据从哪来、到哪去

类比：
  就像追踪快递的运输路线——
  从发货（入口方法）到收货（最终调用），记录每一个中转站。
"""

from __future__ import annotations

from graph.state import GraphState, NodeContext


def trace_data_flow(state: GraphState, ctx: NodeContext) -> GraphState:
    """追踪代码中的数据流路径。

    扫描源码包中的方法骨架，找出有"关键调用"（key_calls）的方法，
    记录它们的调用链。这些调用链帮助后续节点判断数据是否经过了正确的处理。

    参数:
        state: 共享状态，包含 source_package
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 data_flow_paths 字段
    """
    source_package = (
        state.get("source_package", {})
        if isinstance(state.get("source_package", {}), dict)
        else {}
    )
    files = source_package.get("files", []) if isinstance(source_package, dict) else []

    traced_paths = []  # 有调用链的方法列表
    entry_files = []  # 所有扫描过的文件路径（入口文件）
    for source_file in files:
        if not isinstance(source_file, dict):
            continue
        path = source_file.get("path", "")
        entry_files.append(path)
        methods = (
            source_file.get("methods") or source_file.get("method_skeletons") or []
        )
        for method in methods:
            if not isinstance(method, dict):
                continue
            key_calls = method.get("key_calls", []) or []
            # 只记录有关键调用的方法（这些方法参与了数据流）
            if key_calls:
                traced_paths.append(
                    {
                        "path": path,  # 所在文件
                        "signature": method.get("signature", "unknown"),  # 方法签名
                        "calls": key_calls,  # 该方法的关键调用列表
                    }
                )

    # 将数据流路径写入共享状态
    state["data_flow_paths"] = {
        "paths": traced_paths,  # 有调用链的方法列表
        "entry_files": entry_files,  # 所有入口文件
        "status": "READY",
    }
    return state
