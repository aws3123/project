"""平凡变更检查节点 — 判断变更是否足够简单以跳过深度分析。

作用：
    在 classifier 之后、impact 之前执行。
    如果判定为平凡变更（纯注释/文档/配置，无风险关键词，行数 < 阈值）：
      1. 设置 state["trivial"] = True
      2. 预填充 risk_score / breakdown / summary / details / recommendations
      3. 后续节点（rag / 并行 Agent / scoring / report）检测到 trivial 标志后跳过 LLM 调用

为什么需要这个节点？
    完整流水线每次执行约 7-16 秒，包含 5-7 次 LLM 调用、~16500 tokens。
    但 30-40% 的 PR 是平凡变更（注释修改、文档更新、配置调整），
    这些 PR 不需要安全审计、性能分析或 RAG 检索。
    triviality_check 可以直接跳过这些重计算，节省成本。
"""

from __future__ import annotations

from graph.state import GraphState, NodeContext

# 平凡变更阈值：变更行数（新增+删除）低于此值才进入平凡判定
TRIVIAL_DIFF_THRESHOLD = 20

# 纯文档/配置文件后缀 — 如果所有变更文件都是这些类型，视为平凡
DOC_FILE_SUFFIXES = (".md", ".txt", ".rst", ".adoc", ".license", "license")
CONFIG_FILE_SUFFIXES = (
    ".yml", ".yaml", ".json", ".xml", ".properties",
    ".ini", ".env", ".toml", ".conf", ".cfg",
)

# 注释行前缀（覆盖主流语言）
COMMENT_PREFIXES = ("#", "//", "*", "/*", "*/", "<!--", "--", "!")


def _is_comment_or_blank(line: str) -> bool:
    """判断一行是否为注释行或空行。"""
    stripped = line.strip()
    if not stripped:
        return True
    return any(stripped.startswith(prefix) for prefix in COMMENT_PREFIXES)


def _is_doc_or_config_file(path: str) -> bool:
    """判断文件是否为纯文档或配置文件。"""
    path_lower = path.lower()
    return path_lower.endswith(DOC_FILE_SUFFIXES + CONFIG_FILE_SUFFIXES)


def check_triviality(state: GraphState, ctx: NodeContext) -> GraphState:
    """平凡变更检查节点的主函数。

    判定逻辑（全部满足才视为平凡）：
      1. diff 行数 < 20（新增+删除）
      2. 不含核心风险关键词（DELETE/DROP/password/secret 等）
      3. 满足以下之一：
         a. 所有变更文件都是文档/配置文件
         b. 所有新增行都是注释或空行

    如果判定为平凡，预填充所有结果字段，后续节点检测 trivial 标志后短路返回。
    """
    diff_analysis = state.get("diff_analysis", {})
    diff_summary = diff_analysis.get("summary", {})
    diff_size = diff_summary.get("added_lines", 0) + diff_summary.get("deleted_lines", 0)
    files = diff_analysis.get("files", [])

    # 条件1：变更行数 >= 阈值 → 非平凡
    if diff_size >= TRIVIAL_DIFF_THRESHOLD:
        state["trivial"] = False
        return state

    # 条件2：含核心风险关键词 → 非平凡
    # 延迟导入避免循环依赖
    from graph.agent_selector import CORE_RISK_KEYWORDS
    for f in files:
        diff_text = f.get("diff", "").lower()
        if any(kw.lower() in diff_text for kw in CORE_RISK_KEYWORDS):
            state["trivial"] = False
            return state

    # 条件3a：所有文件都是文档/配置文件
    all_doc_or_config = (
        all(_is_doc_or_config_file(f.get("path", "")) for f in files)
        if files
        else False
    )

    # 条件3b：所有新增行都是注释/空行
    all_comment_lines = True
    for f in files:
        diff_text = f.get("diff", "")
        for line in diff_text.split("\n"):
            # 跳过 diff 元信息行（+++、---、@@等）
            if line.startswith(("+++", "---", "@@", "diff ", "index ")):
                continue
            # 新增行（以 + 开头）检查是否为注释
            if line.startswith("+"):
                content = line[1:]
                if not _is_comment_or_blank(content):
                    all_comment_lines = False
                    break
        if not all_comment_lines:
            break

    is_trivial = all_doc_or_config or all_comment_lines

    if is_trivial:
        state["trivial"] = True
        layers = state.get("classification", {}).get("layers", [])
        # 预填充结果字段，后续节点会跳过重计算
        state["risk_score"] = 0.1
        state["breakdown"] = [
            {"dimension": "规则检查", "score": 0, "count": 0},
            {"dimension": "安全审计", "score": 0, "count": 0},
            {"dimension": "性能分析", "score": 0, "count": 0},
            {"dimension": "历史关联", "score": 0, "count": 0},
            {"dimension": "影响范围", "score": 0, "count": 0},
            {"dimension": "测试覆盖", "score": 0},
        ]
        state["need_human_review"] = False
        state["force_human_review"] = False
        state["cross_validated_findings"] = []
        state["summary"] = (
            f"变更判定为低风险（平凡变更），涉及 {diff_size} 行，"
            f"层级: {', '.join(layers) if layers else '未知'}"
        )
        state["details"] = ["本次变更仅涉及注释/文档/配置，未检测到代码逻辑变更。"]
        state["recommendations"] = [
            {"title": "无需特别关注", "detail": "本次变更为平凡变更，风险极低。"}
        ]
    else:
        state["trivial"] = False

    return state
