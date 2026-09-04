"""
SQL 风险检查工具
========================

作用：
    检查代码变更中是否包含潜在的破坏性 SQL 语句（如 DELETE）。
    这类操作可能导致数据丢失，需要特别关注。

为什么 DELETE 危险？
    DELETE 语句会永久删除数据库中的数据。
    如果没有 WHERE 条件，会删除整张表的数据；
    即使有 WHERE 条件，也可能误删重要数据。
    建议改用"软删除"（更新状态字段）而不是物理删除。

检查逻辑：
    遍历每个文件的 diff，逐行查找是否包含 "DELETE" 关键字。
    如果找到，就报告一个高严重程度的发现。
"""

# annotations 延迟求值
from __future__ import annotations

# 导入工具基础类型
from tools.base import Tool, ToolContext, ToolResult


class SQLRiskCheckerTool(Tool):
    """SQL 风险检查工具。

    检查代码变更中是否包含潜在的破坏性 SQL 语句。
    """

    # 工具的唯一标识符
    name = "sql_risk_checker"

    def run(self, payload: dict, context: ToolContext) -> ToolResult:
        """执行 SQL 风险检查。

        参数 payload：
            - files: 文件列表，每个文件包含 path（路径）和 diff（变更内容）

        返回：
            ToolResult，包含检查结果列表（findings）
        """
        findings = []  # 存放所有发现的问题

        # 遍历每个文件
        for file in payload.get("files", []):
            # 逐行扫描 diff 内容，enumerate 同时获取行号（从 1 开始）
            for line_number, line in enumerate(
                file.get("diff", "").splitlines(), start=1
            ):
                # 如果这一行包含 DELETE（不区分大小写），说明可能有破坏性操作
                if "DELETE" in line.upper():
                    findings.append(
                        {
                            "severity": "HIGH",  # 严重程度：高
                            "category": "sql",  # 分类：SQL 相关
                            "title": "Potential destructive query",  # 标题：潜在的破坏性查询
                            "detail": f"Potential destructive query in {file.get('path')}",  # 详情
                            "file": file.get("path"),  # 所在文件
                            "line": line_number,  # 所在行号
                            "evidence": line,  # 证据：这一行的内容
                            "suggestion": "Add WHERE guard or convert to soft delete",  # 建议
                            "confidence": 0.95,  # 置信度：95%
                        }
                    )
                    break  # 一个文件只报告一次，避免重复

        # 返回检查结果
        return ToolResult(name=self.name, payload={"findings": findings})
