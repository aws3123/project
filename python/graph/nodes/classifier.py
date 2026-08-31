"""代码变更分类节点 —— 判断"这次改动涉及哪些层"。

本模块负责将代码变更按架构层次分类（Controller 层、Service 层、SQL 层等），
帮助后续节点了解变更的影响范围。

类比：
  就像快递分拣——先判断包裹属于哪个区域（楼层），
  再送到对应的处理工位。
"""
from __future__ import annotations

from graph.state import GraphState, NodeContext
from tools.base import ToolContext, ToolResult


def classify_changes(state: GraphState, ctx: NodeContext) -> GraphState:
    """对代码变更进行分层分类。

    1. 调用 test_coverage_checker 工具获取变更元信息
    2. 根据文件路径中的关键词判断每个文件属于哪一层：
       - 路径含 "controller" → controller 层（接口层）
       - 路径含 "service"     → service 层（业务逻辑层）
       - 路径含 "sql"         → sql 层（数据访问层）
       - 其他                 → other（其他层）
    3. 将分类结果写入 state["classification"]

    参数:
        state: 共享状态，包含 diff_analysis 和 request
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 classification 字段
    """
    # 获取 diff 分析结果（由上一个节点 analyze_diff 产出）
    diff_meta = state.get("diff_analysis", {})
    payload = diff_meta or {"files": state["request"].get("files", [])}
    # 调用测试覆盖率检查工具，获取额外的覆盖率信息
    result: ToolResult = ctx.registry.run("test_coverage_checker", payload, ToolContext(task_id=ctx.task_id))
    files = payload.get("files", [])
    # 根据文件路径关键词判断所属架构层
    layers = []
    for file_meta in files:
        path = file_meta.get("path", "")
        if "controller" in path:
            layers.append("controller")  # 接口层：处理 HTTP 请求
        elif "service" in path:
            layers.append("service")     # 业务逻辑层：核心业务代码
        elif "sql" in path:
            layers.append("sql")         # 数据访问层：SQL 语句
        else:
            layers.append("other")       # 其他：工具类、配置等
    # 将分类结果和覆盖率信息写入共享状态
    state["classification"] = {
        "layers": layers or ["other"],  # 涉及的架构层列表
        "summary": result.payload,       # 工具返回的覆盖率等摘要信息
    }
    return state
