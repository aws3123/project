"""
API 破坏性变更检查工具
========================

作用：
    检查代码变更中是否使用了已废弃（@Deprecated）的 API。
    如果用了，说明可能存在"API 契约漂移"——调用了不该用的旧接口。

什么是 @Deprecated？
    Java 中用 @Deprecated 标记"已废弃"的 API，表示这个接口将来会被移除，
    建议改用新的替代方案。如果代码还在用这些旧 API，可能会有兼容性风险。

检查逻辑：
    遍历每个文件的 diff（代码变更），逐行查找是否包含 "@Deprecated"。
    如果找到，就报告一个中等严重程度的发现（finding）。
"""

# annotations 延迟求值
from __future__ import annotations

# 导入工具基础类型
from tools.base import Tool, ToolContext, ToolResult


class APIBreakingCheckerTool(Tool):
    """API 破坏性变更检查工具。

    检查代码变更中是否使用了 @Deprecated 标记的 API。
    """

    # 工具的唯一标识符（用于注册表查找）
    name = "api_breaking_checker"

    def run(self, payload: dict, context: ToolContext) -> ToolResult:
        """执行 API 破坏性变更检查。

        参数 payload：
            - files: 文件列表，每个文件包含 path（路径）和 diff（变更内容）

        返回：
            ToolResult，包含检查结果列表（findings）
        """
        findings = []  # 存放所有发现的问题

        # 遍历每个文件
        for file in payload.get("files", []):
            # 逐行扫描 diff 内容，enumerate 同时获取行号（从 1 开始）
            for line_number, line in enumerate(file.get("diff", "").splitlines(), start=1):
                # 如果这一行包含 @Deprecated，说明使用了已废弃的 API
                if "@Deprecated" in line:
                    findings.append(
                        {
                            "severity": "MEDIUM",           # 严重程度：中等
                            "category": "api",              # 分类：API 相关
                            "title": "Potential API contract drift",  # 标题：API 契约可能漂移
                            "detail": f"Deprecated API usage in {file.get('path')}",  # 详情
                            "file": file.get("path"),       # 所在文件
                            "line": line_number,            # 所在行号
                            "evidence": line,               # 证据：这一行的内容
                            "suggestion": "Review compatibility impact and provide a migration path",  # 建议
                            "confidence": 0.85,             # 置信度：85%
                        }
                    )
                    break  # 一个文件只报告一次，避免重复

        # 返回检查结果
        return ToolResult(name=self.name, payload={"findings": findings})
