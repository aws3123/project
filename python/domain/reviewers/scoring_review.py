"""风险评分领域逻辑 —— 纯函数，包含所有评分公式与文本构建。"""

from __future__ import annotations

from domain.reviewers._findings import AGENT_WEIGHT, SEVERITY_MULTIPLIER, cross_validate

__all__ = [
    "AGENT_WEIGHT",
    "SEVERITY_MULTIPLIER",
    "build_cross_text",
    "build_findings_text",
    "build_impact_text",
    "build_scoring_messages",
    "compute_deterministic",
    "cross_validate",
    "parse_scoring_result",
]

#: 参与交叉验证的 Agent 来源顺序
_SOURCES = ("rules", "security", "performance")
_BASE_SCORE = 0.2
_RULE_HIGH_WEIGHT = 0.2
_RULE_HIGH_CAP = 0.5
_SECURITY_HIGH_WEIGHT = 0.25
_SECURITY_HIGH_CAP = 0.5
_PERF_HIGH_WEIGHT = 0.15
_PERF_HIGH_CAP = 0.3
_RAG_CONTEXT_WEIGHT = 0.1
_RAG_CONTEXT_CAP = 0.3
_LOW_COVERAGE_BONUS = 0.2
_COVERAGE_THRESHOLD = 0.8
_IMPACT_WEIGHT = 0.1
_IMPACT_CAP = 0.2
_HUMAN_REVIEW_THRESHOLD = 0.7
_MAX_AFFECTED_FILES_FOR_AUTO_REVIEW = 10

__all__ = [
    "AGENT_WEIGHT",
    "SEVERITY_MULTIPLIER",
    "build_cross_text",
    "build_findings_text",
    "build_impact_text",
    "build_scoring_messages",
    "compute_deterministic",
    "cross_validate",
    "parse_scoring_result",
]

#: 参与交叉验证的 Agent 来源顺序
_SOURCES = ("rules", "security", "performance")


def cross_validate(sources: dict[str, list[dict]]) -> tuple[list[dict], bool]:
    """交叉验证 —— 找出被多个 Agent 同时标记的代码位置。

    Args:
        sources: {source_name: findings}，通常传 {"rules":..., "security":..., "performance":...}。

    Returns:
        (merged_findings, force_human_review)
    """
    file_groups: dict[str, list[dict]] = {}
    for source in _SOURCES:
        for f in sources.get(source, []):
            loc = f"{f.get('file','')}:{f.get('line','')}"
            file_groups.setdefault(loc, []).append({**f, "_source": source})

    merged: list[dict] = []
    force_human = False

    for loc, items in file_groups.items():
        if len(items) == 1:
            merged.append(items[0])
            continue
        # 多 Agent 交叉验证：加权分 = Σ Agent权重 × 严重级别乘数
        weighted_score = sum(
            AGENT_WEIGHT.get(item["_source"], 1)
            * SEVERITY_MULTIPLIER.get(item.get("severity", "LOW"), 1)
            for item in items
        )
        best = max(
            items, key=lambda x: SEVERITY_MULTIPLIER.get(x.get("severity", "LOW"), 0)
        )
        best["confidence"] = min(best.get("confidence", 0.5) * 1.3, 1.0)
        best["cross_validated_by"] = [item["_source"] for item in items]
        best["cross_validation_score"] = weighted_score
        merged.append(best)

        severities = {item.get("severity") for item in items}
        if "HIGH" in severities and any(s in ("LOW", "INFO") for s in severities):
            force_human = True

    return merged, force_human


def compute_deterministic(
    rule_findings: list[dict],
    security_findings: list[dict],
    performance_findings: list[dict],
    rag_context: list,
    impact_radius: dict,
    coverage: float,
    force_human: bool,
) -> dict:
    """确定性评分（降级模式）—— 加权公式计算风险分。

    Returns:
        {"risk_score": float, "breakdown": list, "need_human_review": bool}
    """
    impact_score = impact_radius.get("total_impact_score", 0)
    affected_count = len(impact_radius.get("affected_files", []))

    score = _BASE_SCORE
    score += min(
        len([f for f in rule_findings if f.get("severity") == "HIGH"])
        * _RULE_HIGH_WEIGHT,
        _RULE_HIGH_CAP,
    )
    score += min(
        len([f for f in security_findings if f.get("severity") == "HIGH"])
        * _SECURITY_HIGH_WEIGHT,
        _SECURITY_HIGH_CAP,
    )
    score += min(
        len([f for f in performance_findings if f.get("severity") == "HIGH"])
        * _PERF_HIGH_WEIGHT,
        _PERF_HIGH_CAP,
    )
    score += min(len(rag_context) * _RAG_CONTEXT_WEIGHT, _RAG_CONTEXT_CAP)
    score += _LOW_COVERAGE_BONUS if coverage < _COVERAGE_THRESHOLD else 0
    score += min(impact_score * _IMPACT_WEIGHT, _IMPACT_CAP)
    score = min(score, 1.0)

    breakdown = [
        {
            "dimension": "规则检查",
            "score": min(len(rule_findings) * 10, 100),
            "count": len(rule_findings),
        },
        {
            "dimension": "安全审计",
            "score": min(len(security_findings) * 15, 100),
            "count": len(security_findings),
        },
        {
            "dimension": "性能分析",
            "score": min(len(performance_findings) * 10, 100),
            "count": len(performance_findings),
        },
        {
            "dimension": "历史关联",
            "score": min(len(rag_context) * 10, 100),
            "count": len(rag_context),
        },
        {
            "dimension": "影响范围",
            "score": min(affected_count * 10, 100),
            "count": affected_count,
        },
        {"dimension": "测试覆盖", "score": int((1 - coverage) * 100)},
    ]
    need_human = (
        score >= _HUMAN_REVIEW_THRESHOLD
        or force_human
        or affected_count > _MAX_AFFECTED_FILES_FOR_AUTO_REVIEW
    )
    return {
        "risk_score": score,
        "breakdown": breakdown,
        "need_human_review": need_human,
    }


def build_findings_text(
    rule_findings: list[dict],
    security_findings: list[dict],
    performance_findings: list[dict],
) -> str:
    """构建发现摘要文本（最多取前 15 条）。"""
    return "\n".join(
        f"- [{f.get('severity','INFO')}] [{f.get('category','')}] {f.get('title','')}: {f.get('detail','')}"
        for f in (rule_findings + security_findings + performance_findings)[:15]
    )


def build_cross_text(cross_merged: list[dict], force_human: bool) -> str:
    """构建交叉验证文本（多 Agent 共识的发现 + 矛盾提示）。"""
    cross_text = ""
    if cross_merged:
        cross_items = [f for f in cross_merged if f.get("cross_validated_by")]
        if cross_items:
            cross_text = "## 交叉验证发现（多 Agent 共识）\n" + "\n".join(
                f"- [{f.get('severity','')}] {f.get('title','')} (验证方: {', '.join(f.get('cross_validated_by',[]))}, 加权分: {f.get('cross_validation_score',0):.1f})"
                for f in cross_items[:5]
            )
    if force_human:
        cross_text += "\n\n⚠️ 发现 Agent 间矛盾判定，建议强制人工复核。"
    return cross_text


def build_impact_text(impact_radius: dict) -> str:
    """构建影响范围文本。"""
    if not impact_radius:
        return ""
    impact_score = impact_radius.get("total_impact_score", 0)
    return (
        f"## 变更影响范围\n"
        f"直接影响文件: {impact_radius.get('changed_files', [])}\n"
        f"间接影响文件: {impact_radius.get('affected_files', [])}\n"
        f"影响面评分: {impact_score:.1f} (0=无影响, 越高影响越大)\n"
    )


def build_scoring_messages(
    findings_text: str,
    cross_text: str,
    impact_text: str,
    rag_analysis: str,
    coverage: float,
) -> list[dict]:
    """构建 LLM 结构化评分消息（system + user）。"""
    return [
        {
            "role": "system",
            "content": "你是代码审查风险评估专家。基于多 Agent 分析结果（规则检查、安全审计、性能分析、历史关联、变更影响范围），评估风险。输出 JSON 格式。",
        },
        {
            "role": "user",
            "content": (
                f"## 综合分析结果\n{findings_text or '无'}\n\n"
                f"{cross_text}\n\n"
                f"{impact_text}\n"
                f"## 历史事故关联\n{rag_analysis or '无'}\n\n"
                f"## 测试覆盖率\n{coverage:.0%}\n\n"
                "请评估风险，输出 risk_score (0-100整数)、breakdown (维度含安全/性能/稳定性/数据一致性/兼容性/影响范围，每项含dimension/score/reason)、"
                "need_human_review (bool) 和 risk_summary (一句话总结)。"
            ),
        },
    ]


def parse_scoring_result(result: dict, force_human: bool) -> dict:
    """解析 LLM 结构化评分结果（0-100 → 0-1），并叠加 force_human。"""
    risk_score = result.get("risk_score", 0)
    breakdown = result.get("breakdown", [])
    return {
        "risk_score": risk_score / 100.0,
        "breakdown": [
            {
                "dimension": item.get("dimension", "unknown"),
                "score": item.get("score", 0),
                "reason": item.get("reason", ""),
            }
            for item in breakdown
        ],
        "need_human_review": bool(result.get("need_human_review", False))
        or bool(force_human),
        "risk_summary": result.get("risk_summary", ""),
    }
