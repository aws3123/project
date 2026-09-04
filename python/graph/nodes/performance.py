"""性能分析节点 —— 检查代码变更中的性能风险。

本模块负责检测代码变更中的性能问题，与安全审计节点类似，也采用"双重检查"策略：
1. 确定性扫描（规则匹配）：用正则表达式匹配常见性能问题（N+1 查询、循环内 IO 等）
2. LLM 审计（智能分析）：把代码发给大模型，让它像性能专家一样审查

常见检测模式：
  - N+1 查询：循环内执行数据库查询，每次循环都查一次 → 应该批量查询
  - 循环内 HTTP 请求：每次循环都发网络请求 → 应该批量或异步
  - SELECT *：查询所有字段 → 应该只查需要的列
  - 大粒度同步锁：synchronized 范围太大 → 应该用细粒度锁

类比：
  就像体检——确定性扫描是"常规指标检查"（血压、心率），
  LLM 审计是"专家会诊"（综合判断复杂问题）。
"""
from __future__ import annotations

from domain.shared.diff_extractor import build_diff_snippet
from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError


# 确定性性能模式列表
# 每个元素：(正则表达式, 标题, 严重程度, 详情, 修复建议)
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


def _deterministic_scan(state: GraphState) -> list[dict]:
    """确定性性能扫描 —— 用正则表达式逐行匹配代码变更。

    扫描策略：
    1. 单行匹配：逐行检查是否命中性能模式
    2. 跨行匹配：检查 for 循环的下一行是否有数据库查询（N+1 检测）

    参数:
        state: 共享状态，包含 diff_analysis

    返回:
        发现的性能问题列表
    """
    import re
    findings = []
    for f in state.get("diff_analysis", {}).get("files", []):
        path = f.get("path", "")
        diff = f.get("diff", "")
        lines = diff.splitlines()

        # 第一轮：单行模式匹配
        for idx, line in enumerate(lines, start=1):
            for pattern, title, weight, detail, suggestion in DETERMINISTIC_PATTERNS:
                if line.startswith("+") and re.search(pattern, line):
                    # 根据中文严重程度映射为英文级别
                    severity = "HIGH" if weight == "高" else ("MEDIUM" if weight == "中" else "LOW")
                    findings.append({
                        "severity": severity,
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
        # 为什么单独检测？因为 for 循环和查询可能不在同一行
        for idx, line in enumerate(lines[:-1], start=1):
            if not line.startswith("+"):
                continue
            current = line.lower()
            nxt = lines[idx].lower()
            # 判断当前行是否是 for 循环
            is_loop_line = ("for " in current and current.rstrip().endswith(":")) or ("for(" in current)
            # 判断下一行是否有数据库查询调用
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


def analyze_performance(state: GraphState, ctx: NodeContext) -> GraphState:
    """性能审计主函数 —— 结合确定性扫描和 LLM 审计。

    执行策略（确定性扫描前置，保证降级安全）：
    1. 先执行确定性扫描 → 立即写入 state（即使后续 LLM 超时，基础结果已落盘）
    2. 如果有 LLM 客户端 → 调用 LLM 审计，补充更隐蔽的问题
    3. 合并去重：以确定性扫描为基础，补充 LLM 发现的新问题

    参数:
        state: 共享状态
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 performance_findings 字段
    """
    # ── 第一步：确定性扫描前置（保证降级安全）──────────────────────
    # 先执行确定性扫描并立即写入 state，这样即使后续 LLM 调用超时，
    # 并行层的断点恢复也能拿到基础结果，不会完全丢失性能审计。
    det_findings = _deterministic_scan(state)
    state["performance_findings"] = det_findings  # 先落盘，后续 LLM 成功会覆盖

    # 没有 LLM 客户端 → 降级模式，直接用确定性扫描结果
    if ctx.llm_client is None:
        state.setdefault("tool_logs", []).append({
            "node": "performance",
            "method": "deterministic_only",
            "findings_count": len(det_findings),
            "status": "degraded",
        })
        return state

    # ── 第二步：提取代码片段，准备 LLM 审计 ────────────────────────
    files = state.get("diff_analysis", {}).get("files", [])
    impact_radius = state.get("impact_radius")
    code_graph = state.get("code_graph")
    diff_snippet, method_names = build_diff_snippet(
        files, max_files=5, max_chars_per_file=2500, max_chars_total=6000,
        impact_radius=impact_radius, code_graph=code_graph,
    )

    if not diff_snippet.strip():
        # 无 diff 内容，跳过 LLM，保留确定性扫描结果
        state.setdefault("tool_logs", []).append({
            "node": "performance",
            "method": "deterministic_only",
            "findings_count": len(det_findings),
            "status": "no_diff_for_llm",
        })
        return state

    # ── 第三步：LLM 审计（可选增强）────────────────────────────────
    # 构建方法上下文提示
    method_context = ""
    if method_names:
        method_context = f"\n涉及方法: {', '.join(method_names[:10])}\n"

    # 构建 LLM 消息
    messages = [
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

    # 调用 LLM 进行性能审计
    llm_status = "success"
    try:
        result = ctx.llm_client.chat(messages=messages, max_tokens=1024)
        import json
        data = json.loads(result) if isinstance(result, str) else result
        llm_findings = data.get("findings", []) if isinstance(data, dict) else []
    except Exception:
        llm_findings = []  # LLM 失败时降级：保留确定性扫描结果
        llm_status = "llm_failed"

    # ── 第四步：合并去重 ────────────────────────────────────────────
    seen = {(f.get("file"), f.get("line"), f.get("title")) for f in det_findings}
    llm_new_count = 0
    for lf in llm_findings:
        key = (lf.get("file"), lf.get("line"), lf.get("title"))
        if key not in seen:
            det_findings.append({
                "severity": lf.get("severity", "LOW"),
                "category": lf.get("category", "performance"),
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

    # 更新最终结果（包含确定性 + LLM 补充）
    state["performance_findings"] = det_findings
    state.setdefault("tool_logs", []).append({
        "node": "performance",
        "method": "deterministic+llm",
        "det_findings_count": len(det_findings) - llm_new_count,
        "llm_findings_count": llm_new_count,
        "llm_status": llm_status,
        "status": "success",
    })
    return state
