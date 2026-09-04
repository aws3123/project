"""审查发现公共逻辑 —— 被 security/performance 等审查器共享。

parse_llm_response / merge_findings 在多个"确定性 + LLM"双通道审查器中
结构完全一致，抽到此处避免逐个复制。
"""
from __future__ import annotations

import json


def parse_llm_response(result) -> list[dict]:
    """解析 LLM 返回（str 或 dict）为 findings 列表。"""
    data = json.loads(result) if isinstance(result, str) else result
    return data.get("findings", []) if isinstance(data, dict) else []


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