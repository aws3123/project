"""平凡变更判定领域逻辑 —— 纯函数，判断变更是否可跳过深度分析。"""
from __future__ import annotations

# 平凡变更阈值：变更行数（新增+删除）低于此值才进入平凡判定
TRIVIAL_DIFF_THRESHOLD = 20

# 纯文档/配置文件后缀
DOC_FILE_SUFFIXES = (".md", ".txt", ".rst", ".adoc", ".license", "license")
CONFIG_FILE_SUFFIXES = (
    ".yml", ".yaml", ".json", ".xml", ".properties",
    ".ini", ".env", ".toml", ".conf", ".cfg",
)

# 注释行前缀（覆盖主流语言）
COMMENT_PREFIXES = ("#", "//", "*", "/*", "*/", "<!--", "--", "!")

__all__ = [
    "TRIVIAL_DIFF_THRESHOLD",
    "DOC_FILE_SUFFIXES",
    "CONFIG_FILE_SUFFIXES",
    "COMMENT_PREFIXES",
    "is_comment_or_blank",
    "is_doc_or_config_file",
    "is_trivial",
]


def is_comment_or_blank(line: str) -> bool:
    """判断一行是否为注释行或空行。"""
    stripped = line.strip()
    if not stripped:
        return True
    return any(stripped.startswith(prefix) for prefix in COMMENT_PREFIXES)


def is_doc_or_config_file(path: str) -> bool:
    """判断文件是否为纯文档或配置文件。"""
    path_lower = path.lower()
    return path_lower.endswith(DOC_FILE_SUFFIXES + CONFIG_FILE_SUFFIXES)


def is_trivial(
    diff_analysis: dict,
    risk_keywords: list[str],
    threshold: int = TRIVIAL_DIFF_THRESHOLD,
) -> bool:
    """判定变更是否为平凡变更（纯注释/文档/配置，无风险关键词）。

    条件（全部满足才为平凡）：
      1. diff 行数 < 阈值（新增+删除）
      2. 不含核心风险关键词
      3. 满足以下之一：
         a. 所有变更文件都是文档/配置文件
         b. 所有新增行都是注释或空行

    Args:
        diff_analysis: state 中的 diff 分析结果。
        risk_keywords: 核心风险关键词列表（由节点从 graph 层注入，避免 domain 依赖 graph）。

    Returns:
        是否平凡。
    """
    diff_summary = diff_analysis.get("summary", {})
    diff_size = diff_summary.get("added_lines", 0) + diff_summary.get("deleted_lines", 0)
    files = diff_analysis.get("files", [])

    # 条件1：变更行数 >= 阈值 → 非平凡
    if diff_size >= threshold:
        return False

    # 条件2：含核心风险关键词 → 非平凡
    for f in files:
        diff_text = f.get("diff", "").lower()
        if any(kw.lower() in diff_text for kw in risk_keywords):
            return False

    # 条件3a：所有文件都是文档/配置文件
    all_doc_or_config = (
        all(is_doc_or_config_file(f.get("path", "")) for f in files)
        if files
        else False
    )

    # 条件3b：所有新增行都是注释/空行
    all_comment_lines = True
    for f in files:
        diff_text = f.get("diff", "")
        for line in diff_text.split("\n"):
            if line.startswith(("+++", "---", "@@", "diff ", "index ")):
                continue
            if line.startswith("+"):
                content = line[1:]
                if not is_comment_or_blank(content):
                    all_comment_lines = False
                    break
        if not all_comment_lines:
            break

    return all_doc_or_config or all_comment_lines


def prefilled_fields(layers: list[str], diff_size: int) -> dict:
    """平凡变更的预填充结果（risk/breakdown/summary/details/recommendations）。"""
    return {
        "risk_score": 0.1,
        "breakdown": [
            {"dimension": "规则检查", "score": 0, "count": 0},
            {"dimension": "安全审计", "score": 0, "count": 0},
            {"dimension": "性能分析", "score": 0, "count": 0},
            {"dimension": "历史关联", "score": 0, "count": 0},
            {"dimension": "影响范围", "score": 0, "count": 0},
            {"dimension": "测试覆盖", "score": 0},
        ],
        "need_human_review": False,
        "force_human_review": False,
        "cross_validated_findings": [],
        "summary": (
            f"变更判定为低风险（平凡变更），涉及 {diff_size} 行，"
            f"层级: {', '.join(layers) if layers else '未知'}"
        ),
        "details": ["本次变更仅涉及注释/文档/配置，未检测到代码逻辑变更。"],
        "recommendations": [
            {"title": "无需特别关注", "detail": "本次变更为平凡变更，风险极低。"}
        ],
    }