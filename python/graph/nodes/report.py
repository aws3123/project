"""报告生成节点 —— 把分析结果"翻译"成人类可读的审查报告。

本模块负责生成最终的审查报告，包括：
- summary：整体评估摘要（2-3 句话）
- details：具体发现列表（每条一个独立的风险或问题）
- recommendations：可操作的建议列表

执行策略：
1. 有 LLM → 让大模型生成结构化的报告
2. 没有 LLM → 用模板拼接（降级模式，格式固定但信息完整）

类比：
  就像医生写完各项检查后，需要写一份"诊断报告"——
  把检查数据翻译成患者能看懂的文字。
"""
from __future__ import annotations

from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError
from schemas.llm_output import ReportOutput

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


def _template_fallback(state: GraphState) -> None:
    """模板降级模式 —— 没有 LLM 时用固定模板拼接报告。

    从 state 中提取关键数据，按固定格式生成摘要、详情和建议。
    虽然不如 LLM 生成的报告流畅，但基本信息完整。
    """
    risk = int(round((state.get("risk_score") or 0.5) * 100))
    layers = state.get("classification", {}).get("layers", [])
    rule_findings = state.get("rule_findings", [])
    # 按严重级别排序，最严重的排前面
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

    # 生成摘要文本
    state["summary"] = f"整体风险 {risk}/100，涉及层级: {', '.join(layers)}；重点关注: {headline}"
    # 生成详情列表
    state["details"] = [f"{item.get('category','')}: {item.get('detail','')}" for item in top_findings]
    # 生成建议列表
    state["recommendations"] = [
        {
            "title": "提升覆盖率",
            "detail": f"当前覆盖率 {state.get('classification', {}).get('summary', {}).get('coverage', 1):.0%}",
        },
        {
            "title": "关注规则命中",
            "detail": f"发现 {len(rule_findings)} 项规则告警",
        },
    ]


def summarize(state: GraphState, ctx: NodeContext) -> GraphState:
    """报告生成主函数 —— 生成审查报告摘要和建议。

    执行策略：
    1. 平凡变更 → 直接返回预填充结果
    2. 没有 LLM → 模板降级模式
    3. 有 LLM → 让大模型生成报告，失败时降级到模板

    参数:
        state: 共享状态，包含所有前序节点的分析结果
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 summary、details、recommendations 字段
    """
    # 平凡变更 → 直接返回预填充结果（triviality_check 已设置）
    if state.get("trivial"):
        return state

    # 降级模式：没有 LLM 时用模板拼接
    if ctx.llm_client is None:
        _template_fallback(state)
        return state

    # 准备风险评分数据
    risk_score = state.get("risk_score", 0.5)
    if 0 <= risk_score <= 1:
        risk_score = int(round(risk_score * 100))  # 0-1 → 0-100
    else:
        risk_score = int(round(risk_score))

    # 构建风险细分文本
    breakdown = state.get("breakdown", [])
    breakdown_text = "\n".join(
        f"- {item.get('dimension','unknown')}: {item.get('score',0)}分 {item.get('reason','')}"
        for item in breakdown
    )
    # 构建规则发现文本（最多 5 条）
    rule_findings = state.get("rule_findings", [])
    rules_text = "\n".join(
        f"- [{f.get('severity','INFO')}] {f.get('title','')}: {f.get('detail','')} (建议: {f.get('suggestion','无')})"
        for f in rule_findings[:5]
    )
    rag_analysis = state.get("rag_analysis", "")
    risk_summary = state.get("risk_summary", "")

    # 收集 RAG 关联的图片引用
    rag_context = state.get("rag_context", [])
    image_refs_text = ""
    for item in rag_context:
        urls = item.get("image_urls", [])
        if urls:
            for url in urls[:2]:
                title = item.get("topic", "")
                image_refs_text += f"\n- 相关图片: [{title}]({url})"

    # 构建 LLM 消息
    messages = [
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
                f"## 风险评分\n{risk_score}/100\n{risk_summary}\n\n"
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

    # 调用 LLM 生成结构化报告
    try:
        result = ctx.llm_client.chat_structured(
            messages=messages,
            output_schema=ReportOutput,
            max_tokens=1536,
        )
        state["summary"] = result.get("summary", "")
        state["details"] = result.get("details", [])
        state["recommendations"] = result.get("recommendations", [])
    except LLMStructuredOutputError:
        # LLM 输出格式错误 → 降级到模板模式
        _template_fallback(state)

    return state
