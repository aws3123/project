"""报告生成领域逻辑 —— 纯函数：模板降级 + LLM 消息构建。"""
from __future__ import annotations

# 严重级别权重（用于排序发现，最严重的排前面）
SEVERITY_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
# 默认发现（当没有规则问题时使用的占位信息）
DEFAULT_FINDING = {
    "severity": "INFO",
    "category": "general",
    "title": "未发现高优先级规则问题",
    "detail": "No rule findings",
    "confidence": 0.0,
}

__all__ = [
    "SEVERITY_WEIGHT",
    "DEFAULT_FINDING",
    "template_fallback",
    "build_report_messages",
]


def template_fallback(
    risk_score: float,
    layers: list[str],
    rule_findings: list[dict],
    coverage: float,
) -> dict:
    """模板降级模式 —— 无 LLM 时用固定模板拼接报告。

    Returns:
        {"summary": str, "details": list[str], "recommendations": list[dict]}
    """
    risk = int(round((risk_score or 0.5) * 100))
    sorted_findings = sorted(
        rule_findings,
        key=lambda item: (
            SEVERITY_WEIGHT.get(item.get("severity", "INFO"), 0),
            item.get("confidence", 0),
        ),
        reverse=True,
    )
    top_findings = sorted_findings[:3]  # 取前 3 个最严重的问题
    headline = top_findings[0].get("title") if top_findings else None
    if not headline:
        headline = DEFAULT_FINDING["title"]

    summary = f"整体风险 {risk}/100，涉及层级: {', '.join(layers)}；重点关注: {headline}"
    details = [f"{item.get('category','')}: {item.get('detail','')}" for item in top_findings]
    recommendations = [
        {
            "title": "提升覆盖率",
            "detail": f"当前覆盖率 {coverage:.0%}",
        },
        {
            "title": "关注规则命中",
            "detail": f"发现 {len(rule_findings)} 项规则告警",
        },
    ]
    return {"summary": summary, "details": details, "recommendations": recommendations}


def build_report_messages(
    risk_score_value: int,
    risk_summary: str,
    breakdown: list[dict],
    rule_findings: list[dict],
    rag_analysis: str,
    rag_context: list[dict],
) -> list[dict]:
    """构建 LLM 报告消息（system + user）。"""
    breakdown_text = "\n".join(
        f"- {item.get('dimension','unknown')}: {item.get('score',0)}分 {item.get('reason','')}"
        for item in breakdown
    )
    rules_text = "\n".join(
        f"- [{f.get('severity','INFO')}] {f.get('title','')}: {f.get('detail','')} (建议: {f.get('suggestion','无')})"
        for f in rule_findings[:5]
    )
    image_refs_text = ""
    for item in rag_context:
        urls = item.get("image_urls", [])
        if urls:
            for url in urls[:2]:
                title = item.get("topic", "")
                image_refs_text += f"\n- 相关图片: [{title}]({url})"

    return [
        {
            "role": "system",
            "content": (
                "你是代码审查报告专家。基于全面的代码分析结果，生成审查报告摘要和可操作的建议。"
                "输出 JSON 格式。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## 风险评分\n{risk_score_value}/100\n{risk_summary}\n\n"
                f"## 风险细分\n{breakdown_text or '无'}\n\n"
                f"## 规则发现\n{rules_text or '无'}\n\n"
                f"## 历史事故关联\n{rag_analysis or '无'}\n"
                f"## 可用图片引用\n{image_refs_text or '无'}\n\n"
                "请生成审查报告。输出 summary（整体评估，2-3句话）、"
                "details（具体发现列表，每条一个独立的风险或问题）和 "
                "recommendations（3-5条可操作建议，每条含title和detail）。"
                "如果有相关的历史事故图片，请在 details 中适当使用 ![描述](URL) 格式引用图片。"
            ),
        },
    ]