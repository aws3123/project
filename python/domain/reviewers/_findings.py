"""审查发现公共逻辑 —— 被 security/performance 等审查器共享。

- parse_llm_response / merge_findings：多个"确定性 + LLM"双通道审查器共用
- cross_validate：去重(deduplicate)与评分(scoring)都需要的交叉验证逻辑
"""
from __future__ import annotations

import json

# Agent 权重：不同 Agent 的发现对最终评分的贡献权重
AGENT_WEIGHT = {"security": 3, "rules": 2, "performance": 1.5, "rag": 1}
# 严重级别乘数：HIGH 的问题影响是 LOW 的 3 倍
SEVERITY_MULTIPLIER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0.5}


def parse_llm_response(result) -> list[dict]:
    """解析 LLM 返回（str 或 dict）为 findings 列表。"""
    data = json.loads(result) if isinstance(result, str) else result
    return data.get("findings", []) if isinstance(data, dict) else []


def cross_validate(sources: dict[str, list[dict]]) -> tuple[list[dict], bool]:
    """交叉验证 —— 找出被多个 Agent 同时标记的代码位置。

    将 rules/security/performance 的发现按"文件:行号"分组：
    - 同一位置被多个 Agent 发现 → 取最严重做代表，提升置信度，记录 cross_validated_by
    - 同一位置既有 HIGH 又有 LOW/INFO → 判定矛盾，标记强制人工复核

    Args:
        sources: {source_name: findings}。

    Returns:
        (merged_findings, force_human_review)
    """
    file_groups: dict[str, list[dict]] = {}
    for source in ("rules", "security", "performance"):
        for f in sources.get(source, []):
            loc = f"{f.get('file','')}:{f.get('line','')}"
            file_groups.setdefault(loc, []).append({**f, "_source": source})

    merged: list[dict] = []
    force_human = False

    for loc, items in file_groups.items():
        if len(items) == 1:
            merged.append(items[0])
            continue

        weighted_score = sum(
            AGENT_WEIGHT.get(item["_source"], 1) *
            SEVERITY_MULTIPLIER.get(item.get("severity", "LOW"), 1)
            for item in items
        )
        best = max(items, key=lambda x: SEVERITY_MULTIPLIER.get(x.get("severity", "LOW"), 0))
        best["confidence"] = min(best.get("confidence", 0.5) * 1.3, 1.0)
        best["cross_validated_by"] = [item["_source"] for item in items]
        best["cross_validation_score"] = weighted_score
        merged.append(best)

        severities = {item.get("severity") for item in items}
        if "HIGH" in severities and any(s in ("LOW", "INFO") for s in severities):
            force_human = True

    return merged, force_human


def merge_findings(
    det_findings: list[dict],
    llm_findings: list[dict],
    category: str = "security",
) -> tuple[list[dict], int]:
    """合并去重：以 (file, line, title) 为键，返回 (合并后的发现列表, LLM 新增数)。

    Args:
        det_findings: 确定性扫描结果（基础，优先保留）
        llm_findings: LLM 审计补充发现
        category:     发现类别（security / performance），用于 LLM 补充项的默认归属
    """
    seen = {(f.get("file"), f.get("line"), f.get("title")) for f in det_findings}
    merged = list(det_findings)
    llm_new_count = 0
    for lf in llm_findings:
        key = (lf.get("file"), lf.get("line"), lf.get("title"))
        if key not in seen:
            merged.append({
                "severity": lf.get("severity", "LOW"),
                "category": lf.get("category", category),
                "title": lf.get("title", ""),
                "detail": lf.get("detail", ""),
                "file": lf.get("file"),
                "line": lf.get("line"),
                "evidence": lf.get("evidence", ""),
                "suggestion": lf.get("suggestion", ""),
                "confidence": float(lf.get("confidence", 0.7)),
            })
            seen.add(key)
            llm_new_count += 1
    return merged, llm_new_count