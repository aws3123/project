"""影响范围分析节点 —— 判断"这次改动会影响哪些代码"。

本模块负责分析代码变更的影响半径：
1. 解析变更文件的 AST（抽象语法树），提取类、方法等实体和它们之间的调用关系
2. 构建代码知识图谱，找出"改了 A 方法，哪些 B 方法会受影响"

专业概念解释：
  - AST（抽象语法树）：把代码解析成树形结构，方便程序理解代码的含义
    类比：把一篇文章拆成"段落→句子→词语"的结构化表示
  - 知识图谱：用"节点+边"表示实体和关系
    类比：人物关系图——A 调用 B，B 依赖 C，一目了然

为什么优先使用 Java 端预处理结果？
  Java 后端在发送请求前已经用 Tree-sitter 解析了 AST，
  所以 Python 端可以直接用现成的结果，不用重复解析（节省时间）。
"""
from __future__ import annotations

from graph.state import GraphState, NodeContext
from tools.base import ToolContext, ToolResult


def analyze_impact(state: GraphState, ctx: NodeContext) -> GraphState:
    """分析代码变更的影响范围。

    执行流程：
    1. 从 diff_analysis 中提取变更文件列表和路径
    2. 获取 AST 实体和关系（优先用 Java 端预处理结果，否则调用 ast_parser 工具）
    3. 调用 code_knowledge_graph 工具构建代码图谱，计算影响半径
    4. 将实体、关系、图谱数据、影响范围写入共享状态

    参数:
        state: 共享状态，包含 diff_analysis 和 request
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 diff_analysis（含实体/关系）、code_graph、impact_radius
    """
    diff_analysis = state.get("diff_analysis", {})
    files = diff_analysis.get("files", [])
    # 获取变更文件的路径列表
    changed_paths = diff_analysis.get("summary", {}).get("paths", []) or [
        f.get("path", "") for f in files
    ]

    # 优先使用 Java 端预处理的实体/关系（Java 后端已经用 Tree-sitter 解析好了）
    request = state.get("request", {})
    preprocessed_entities = request.get("entities") if request else None
    preprocessed_relations = request.get("relations") if request else None

    if preprocessed_entities is not None and preprocessed_relations is not None:
        # 直接使用 Java 端预处理的结果（更快，避免重复解析）
        ast_entities = preprocessed_entities
        ast_relations = preprocessed_relations
    else:
        # Java 端没有预处理 → 调用 Python 端的 ast_parser 工具解析
        ast_result: ToolResult = ctx.registry.run(
            "ast_parser",
            {"files": files},
            ToolContext(task_id=ctx.task_id),
        )
        ast_entities = ast_result.payload.get("entities", [])  # 代码实体（类、方法等）
        ast_relations = ast_result.payload.get("relations", [])  # 实体间关系（调用、继承等）

    # 调用代码知识图谱工具：输入实体+关系+变更文件 → 输出影响范围
    kg_result: ToolResult = ctx.registry.run(
        "code_knowledge_graph",
        {
            "entities": ast_entities,
            "relations": ast_relations,
            "changed_files": changed_paths,
        },
        ToolContext(task_id=ctx.task_id),
    )

    # 将 AST 实体和关系追加到 diff_analysis 中（供后续节点使用）
    diff_analysis["entities"] = ast_entities
    diff_analysis["relations"] = ast_relations
    state["diff_analysis"] = diff_analysis
    # 代码图谱数据（可视化或进一步分析用）
    state["code_graph"] = kg_result.payload.get("graph_data", {})
    # 影响半径：哪些代码会被这次变更波及
    state["impact_radius"] = kg_result.payload.get("impact", {})

    return state
