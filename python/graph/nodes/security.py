"""安全审计节点 —— 检查代码变更中的安全风险。

本模块负责检测代码变更中的安全问题，采用"双重检查"策略：
1. 确定性扫描（规则匹配）：用正则表达式匹配常见安全问题（硬编码密码、SQL 注入等）
2. LLM 审计（智能分析）：把代码发给大模型，让它像安全专家一样审查

为什么需要两种？
  - 确定性扫描：速度快、结果稳定，但只能发现"已知模式"的问题
  - LLM 审计：能发现更隐蔽的问题（如逻辑漏洞），但可能产生幻觉
  - 两者互补：规则兜底 + AI 增强 = 更全面的安全检查

类比：
  确定性扫描 = 安检门的金属探测器（标准件必报）
  LLM 审计 = 安检员人工复查（能发现非标物品）
"""
from __future__ import annotations

from graph.nodes.diff_extractor import build_diff_snippet
from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError


# 确定性安全模式列表
# 每个元素：(正则表达式, 严重级别, 标题, 详情, 修复建议)
# 这些模式覆盖了常见的安全漏洞（OWASP Top 10 中的高频项）
DETERMINISTIC_PATTERNS = [
    ("password\\s*=\\s*[\"'].*[\"']", "HIGH", "硬编码密码", "代码中直接写入密码字符串", "移至环境变量或密钥管理服务"),
    ("secret\\s*=\\s*[\"'].*[\"']", "HIGH", "硬编码密钥", "代码中直接写入密钥", "移至环境变量或密钥管理服务"),
    ("api_key\\s*=\\s*[\"'].*[\"']", "HIGH", "硬编码 API Key", "代码中直接写入 API 密钥", "移至环境变量"),
    ("execute\\(.*\\+.*\\)", "HIGH", "SQL 注入风险", "字符串拼接构建 SQL 语句", "使用参数化查询"),
    ("innerHTML|document\\.write", "MEDIUM", "XSS 风险", "直接操作 innerHTML 或 document.write", "使用 textContent 或 DOMPurify"),
    ("@RequestMapping.*method.*GET.*password", "MEDIUM", "敏感参数暴露", "密码参数可能在 URL 中暴露", "使用 POST + RequestBody"),
    ("logger\\.(info|debug)\\(.*password", "MEDIUM", "敏感信息日志泄露", "密码可能在日志中泄露", "脱敏处理敏感字段"),
    ("Thread\\.sleep", "LOW", "不安全的线程挂起", "Thread.sleep 可能被用于时序攻击防御", "使用安全随机延迟"),
    ("DES|DESede|ECB", "MEDIUM", "弱加密算法", "使用过时的加密算法", "使用 AES-GCM 或 ChaCha20-Poly1305"),
    ("System\\.exit", "LOW", "非正常退出", "调用 System.exit 可能导致服务不可用", "抛出异常由框架处理"),
]


def _deterministic_scan(state: GraphState) -> list[dict]:
    """确定性安全扫描 —— 用正则表达式逐行匹配代码变更。

    只扫描 diff 中的新增行（以 "+" 开头），因为这些才是本次变更引入的风险。

    参数:
        state: 共享状态，包含 diff_analysis（含文件列表和 diff 内容）

    返回:
        发现的安全问题列表，每项包含 severity、title、file、line 等信息
    """
    import re
    findings = []
    for f in state.get("diff_analysis", {}).get("files", []):
        path = f.get("path", "")
        diff = f.get("diff", "")
        # 逐行扫描 diff 内容
        for idx, line in enumerate(diff.splitlines(), start=1):
            for pattern, severity, title, detail, suggestion in DETERMINISTIC_PATTERNS:
                # 只检查新增行（以 "+" 开头），已删除的行不会引入新风险
                if line.startswith("+") and re.search(pattern, line):
                    findings.append({
                        "severity": severity,
                        "category": "security",
                        "title": title,
                        "detail": f"{detail}: {path}",
                        "file": path,
                        "line": idx,
                        "evidence": line.strip()[:120],  # 截取前 120 字符作为证据
                        "suggestion": suggestion,
                        "confidence": 0.85,  # 正则匹配置信度较高
                    })
    return findings


def audit_security(state: GraphState, ctx: NodeContext) -> GraphState:
    """安全审计主函数 —— 结合确定性扫描和 LLM 审计。

    执行策略（确定性扫描前置，保证降级安全）：
    1. 先执行确定性扫描 → 立即写入 state（即使后续 LLM 超时，基础结果已落盘）
    2. 如果有 LLM 客户端 → 调用 LLM 审计，补充更隐蔽的问题
    3. 合并去重：以确定性扫描为基础，补充 LLM 发现的新问题

    去重逻辑：以 (文件, 行号, 标题) 为唯一键，避免同一问题被重复报告。

    参数:
        state: 共享状态
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 security_findings 字段
    """
    # ── 第一步：确定性扫描前置（保证降级安全）──────────────────────
    # 先执行确定性扫描并立即写入 state，这样即使后续 LLM 调用超时，
    # 并行层的断点恢复也能拿到基础结果，不会完全丢失安全审计。
    det_findings = _deterministic_scan(state)
    state["security_findings"] = det_findings  # 先落盘，后续 LLM 成功会覆盖

    # 没有 LLM 客户端 → 降级模式，直接用确定性扫描结果
    if ctx.llm_client is None:
        state.setdefault("tool_logs", []).append({
            "node": "security",
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
            "node": "security",
            "method": "deterministic_only",
            "findings_count": len(det_findings),
            "status": "no_diff_for_llm",
        })
        return state

    # ── 第三步：LLM 审计（可选增强）────────────────────────────────
    # 构建方法上下文提示（告诉 LLM 涉及了哪些方法）
    method_context = ""
    if method_names:
        method_context = f"\n涉及方法: {', '.join(method_names[:10])}\n"

    # 构建 LLM 消息：系统提示 + 代码变更
    messages = [
        {
            "role": "system",
            "content": (
                "你是应用安全审计专家。分析代码变更中的安全风险，覆盖 OWASP Top 10："
                "SQL注入、XSS、认证绕过、敏感信息泄露、不安全反序列化、硬编码凭证、弱加密。"
                "以下代码按完整方法体展示，请结合方法上下文分析安全风险。"
                "输出 JSON 格式。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## 代码变更{method_context}\n{diff_snippet[:3000]}\n\n"
                "请列出所有安全发现，输出 findings 数组，每项含 severity(HIGH/MEDIUM/LOW)、"
                "category、title、detail、file、line、suggestion(中文)、confidence(0-1)。"
                "若无安全问题，返回空数组。"
            ),
        },
    ]

    # 调用 LLM 进行安全审计
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
    # 用 (文件, 行号, 标题) 三元组作为去重键
    seen = {(f.get("file"), f.get("line"), f.get("title")) for f in det_findings}
    llm_new_count = 0
    for lf in llm_findings:
        key = (lf.get("file"), lf.get("line"), lf.get("title"))
        if key not in seen:
            # LLM 发现了确定性扫描没覆盖到的问题 → 补充进去
            det_findings.append({
                "severity": lf.get("severity", "LOW"),
                "category": lf.get("category", "security"),
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
    state["security_findings"] = det_findings
    state.setdefault("tool_logs", []).append({
        "node": "security",
        "method": "deterministic+llm",
        "det_findings_count": len(det_findings) - llm_new_count,
        "llm_findings_count": llm_new_count,
        "llm_status": llm_status,
        "status": "success",
    })
    return state
