"""性能审查领域逻辑 —— 纯函数，可与流水线解耦独立测试。"""
from __future__ import annotations

import re

from domain.reviewers._findings import merge_findings, parse_llm_response

__all__ = [
    "DETERMINISTIC_PATTERNS",
    "scan_deterministic",
    "build_audit_messages",
    "merge_findings",
    "parse_llm_response",
]

# 确定性性能模式列表
# 每项：(正则表达式, 标题, 严重程度【中文:高/中/低】, 详情, 修复建议)
DETERMINISTIC_PATTERNS = [
    ("for\\s+.*\\(.*\\).*\\{.*\\.(find|query|select|get)", "查询在循环内执行", "高", "N+1 查询风险，循环内调用数据库查询", "批量查询 + 内存聚合，或使用 JOIN"),
    ("for\\s+.*\\(.*\\).*\\{.*http", "网络调用在循环内", "高", "循环内发起 HTTP 请求，每次迭代都建立连接", "批量请求或异步并发"),
    ("new\\s+String\\(", "不必要的字符串对象创建", "低", "new String() 创建不必要的对象", "直接使用字符串字面量"),
    ("\\+\\s*=\\s*.*String", "循环内字符串拼接", "中", "循环内使用 += 拼接字符串，产生大量临时对象", "使用 StringBuilder 或 join()"),
    ("System\\.gc\\(\\)", "显式 GC 调用", "中", "显式调用垃圾回收，可能导致 STW", "移除显式 GC 调用"),
    ("catch.*Exception.*\\{.*\\}", "吞没异常", "中", "catch 块未处理异常，可能隐藏性能问题", "记录日志或重新抛出"),
    ("SELECT \\* FROM", "SELECT * 全字段查询", "中", "SELECT * 拉取不必要字段，增加网络和内存开销", "明确指定需要的列"),
    ("Thread\\.sleep\\(|TimeUnit.*\\.sleep", "硬编码等待时间", "低", "固定 sleep 时间，性能不可控", "使用异步回调或轮询重试"),
    ("synchronized.*\\{", "大粒度的同步锁", "中", "synchronized 块可能成为性能瓶颈", "使用细粒度锁或 Lock-Free 数据结构"),
    ("ArrayList<.*>\\(\\)\\s*;", "未指定初始容量的 ArrayList", "低", "默认容量可能导致多次扩容", "预估容量，指定 initialCapacity"),
]

# 中文严重程度 -> 英文级别
_WEIGHT_TO_SEVERITY = {"高": "HIGH", "中": "MEDIUM", "低": "LOW"}


def scan_deterministic(files: list[dict]) -> list[dict]:
    """确定性性能扫描 —— 正则匹配常见性能问题。

    两轮扫描：
    1. 单行匹配：逐行检查是否命中性能模式
    2. 跨行匹配 / N+1：检查 for 循环后续行是否有数据库查询

    Args:
        files: diff 分析产出的文件列表（每项含 path、diff）。

    Returns:
        性能发现列表。
    """
    findings = []
    for f in files:
        path = f.get("path", "")
        diff = f.get("diff", "")
        lines = diff.splitlines()

        # 第一轮：单行模式匹配
        for idx, line in enumerate(lines, start=1):
            for pattern, title, weight, detail, suggestion in DETERMINISTIC_PATTERNS:
                if line.startswith("+") and re.search(pattern, line):
                    findings.append({
                        "severity": _WEIGHT_TO_SEVERITY.get(weight, "MEDIUM"),
                        "category": "performance",
                        "title": title,
                        "detail": f"{detail}: {path}",
                        "file": path,
                        "line": idx,
                        "evidence": line.strip()[:120],
                        "suggestion": suggestion,
                        "confidence": 0.80,
                    })

        # 第二轮：跨行匹配 —— 检测 for 循环后续行是否有数据库查询（N+1 模式）
        for idx, line in enumerate(lines[:-1], start=1):
            if not line.startswith("+"):
                continue
            current = line.lower()
            nxt = lines[idx].lower()
            is_loop_line = ("for " in current and current.rstrip().endswith(":")) or ("for(" in current)
            has_query_call = any(token in nxt for token in (".find(", ".query(", ".select(", ".get("))
            if is_loop_line and lines[idx].startswith("+") and has_query_call:
                findings.append({
                    "severity": "HIGH",
                    "category": "performance",
                    "title": "查询在循环内执行",
                    "detail": f"N+1 查询风险，循环后续行调用查询: {path}",
                    "file": path,
                    "line": idx + 1,
                    "evidence": lines[idx].strip()[:120],
                    "suggestion": "批量查询 + 内存聚合，或使用 JOIN",
                    "confidence": 0.80,
                })
    return findings


def build_audit_messages(diff_snippet: str, method_names: list[str]) -> list[dict]:
    """构建 LLM 性能审计消息（system + user），纯函数。"""
    method_context = ""
    if method_names:
        method_context = f"\n涉及方法: {', '.join(method_names[:10])}\n"
    return [
        {
            "role": "system",
            "content": (
                "你是应用性能分析专家。分析代码变更中的性能风险：N+1查询、循环内IO、"
                "缓存策略缺失、大对象/大事务、资源未关闭、同步阻塞。"
                "以下代码按完整方法体展示，请结合方法上下文分析性能问题。"
                "输出 JSON 格式。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## 代码变更{method_context}\n{diff_snippet[:3000]}\n\n"
                "请列出所有性能发现，输出 findings 数组，每项含 severity(HIGH/MEDIUM/LOW)、"
                "category、title、detail、file、line、suggestion(中文)、confidence(0-1)。"
                "若无性能问题，返回空数组。"
            ),
        },
    ]