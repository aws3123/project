"""RAG 领域逻辑 —— 纯函数，包含检索查询构建、结果格式化与 LLM 文本构建。"""

from __future__ import annotations

__all__ = [
    "build_code_metadata",
    "build_context_text",
    "build_rag_messages",
    "build_retrieval_query",
    "format_retrieval_results",
]

#: 检索时最多携带的代码实体数量（避免查询过长）
_MAX_ENTITIES = 10
#: 每个检索项的代码内容在 context 中展示的最大字符数
_CODE_EXCERPT = 200
#: context 中的 diff 片段最大字符数
_DIFF_MAX_CHARS = 1000


def build_code_metadata(state: dict) -> list[dict] | None:
    """从请求中提取代码实体元数据（用于增强检索）。

    从 Java BFF 预处理的实体列表中，提取 name/kind/language/signature。
    最多取 10 个实体（避免查询过长）。
    """
    request = state.get("request", {}) or {}
    entities = request.get("entities", [])
    if not entities:
        return None

    code_metadata: list[dict] = []
    for entity in entities[:_MAX_ENTITIES]:
        code_metadata.append(
            {
                "name": entity.get("name", ""),
                "kind": entity.get("kind", "unknown"),
                "language": entity.get("language", ""),
                "signature": entity.get("signature", ""),
            }
        )
    return code_metadata or None


def build_retrieval_query(state: dict) -> str:
    """从层级 + diff 路径拼接自然语言检索查询。"""
    classification = state.get("classification", {})
    layers = classification.get("layers", [])
    nl_query = " ".join(layers) if layers else "general"
    if diff := state.get("diff_analysis", {}):
        if paths := diff.get("summary", {}).get("paths", []):
            nl_query = nl_query + " " + " ".join(paths)
    return nl_query


def format_retrieval_results(fused: list[dict]) -> list[dict]:
    """将检索服务的原始结果格式化为向后兼容的 rag_context 结构。"""
    return [
        {
            "source": item.get("source", "unknown"),
            "topic": item.get("title", "unknown"),
            "snippet": (item.get("nl_description", "") or item.get("snippet", ""))
            + "\n"
            + (item.get("code_content", "") or "")[:_CODE_EXCERPT],
            "score": item.get("score", 0),
            "image_urls": item.get("image_urls", []),
            "image_texts": item.get("image_texts", []),
            "citation": {
                "source": item.get("source", "unknown"),
                "title": item.get("title", "unknown"),
                "snippet": item.get("nl_description", item.get("snippet", "")),
                "image_urls": item.get("image_urls", []),
                "entity_name": item.get("entity_name", ""),
                "code_content": item.get("code_content", ""),
            },
        }
        for item in fused
    ]


def build_context_text(budgeted: list[dict]) -> str:
    """把截断后的检索结果拼接为供 LLM 阅读的上下文文本。"""
    context_lines = []
    for item in budgeted:
        nl = item.get("nl_description", "") or item.get("snippet", "")
        code = item.get("code_content", "")
        line = f"- [{item.get('title','')}] {nl}"
        if code:
            line += f"\n  代码: {code[:_CODE_EXCERPT]}"
        line += f" (来源: {item.get('source','')})"
        image_urls = item.get("image_urls", [])
        if image_urls:
            img_refs = ", ".join(image_urls[:3])
            line += f" [相关图片: {img_refs}]"
        context_lines.append(line)
    return "\n".join(context_lines)


def build_rag_messages(context_text: str, diff_snippet: str) -> list[dict]:
    """构建 RAG 分析的 LLM 消息。"""
    return [
        {
            "role": "system",
            "content": (
                "你是代码审查专家。根据历史事故记录，分析本次代码变更与历史事故的风险关联。"
                "输出 JSON 格式。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## 历史事故记录\n{context_text}\n\n"
                f"## 本次代码变更\n{diff_snippet[:_DIFF_MAX_CHARS]}\n\n"
                "请分析本次变更与历史事故的风险关联，输出 related_incidents（相关事故标题列表）、"
                "risk_association（风险关联分析，一句话）和 suggested_actions（建议措施列表）。"
                "如果历史事故记录包含相关图片链接，请在分析中使用 ![描述](URL) 语法引用相关图片。"
            ),
        },
    ]
