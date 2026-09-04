"""安全审查领域逻辑 —— 纯函数，可与流水线解耦独立测试。"""
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

# 确定性安全模式列表
# 每项：(正则表达式, 严重级别, 标题, 详情, 修复建议)
# 覆盖 OWASP Top 10 中的高频漏洞模式
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


def scan_deterministic(files: list[dict]) -> list[dict]:
    """确定性安全扫描 —— 只扫描 diff 中的新增行（以 + 开头）。

    Args:
        files: diff 分析产出的文件列表（每项含 path、diff）。

    Returns:
        安全发现列表，每项含 severity、category、title、file、line、evidence、suggestion、confidence。
    """
    findings = []
    for f in files:
        path = f.get("path", "")
        diff = f.get("diff", "")
        for idx, line in enumerate(diff.splitlines(), start=1):
            for pattern, severity, title, detail, suggestion in DETERMINISTIC_PATTERNS:
                if line.startswith("+") and re.search(pattern, line):
                    findings.append({
                        "severity": severity,
                        "category": "security",
                        "title": title,
                        "detail": f"{detail}: {path}",
                        "file": path,
                        "line": idx,
                        "evidence": line.strip()[:120],
                        "suggestion": suggestion,
                        "confidence": 0.85,
                    })
    return findings


def build_audit_messages(diff_snippet: str, method_names: list[str]) -> list[dict]:
    """构建 LLM 安全审计消息（system + user），纯函数。"""
    method_context = ""
    if method_names:
        method_context = f"\n涉及方法: {', '.join(method_names[:10])}\n"
    return [
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