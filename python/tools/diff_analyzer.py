"""
Diff 分析工具
========================

作用：
    分析代码变更（diff）的基本统计信息：
    - 新增了多少行
    - 删除了多少行
    - 涉及哪些编程语言
    - 是否存在"大变更"风险标志

什么是 diff？
    diff 是代码变更的文本表示，用 + 表示新增行，- 表示删除行。
    例如：
        + new_line    # 新增了一行
        - old_line    # 删除了一行

检查逻辑：
    遍历每个文件的 diff，统计 + 和 - 开头的行数，
    根据文件扩展名推断编程语言，
    如果总变更行数超过 200 行，标记为"大变更"风险。
"""

# annotations 延迟求值
from __future__ import annotations

# 导入工具基础类型
from tools.base import Tool, ToolContext, ToolResult


class DiffAnalyzerTool(Tool):
    """Diff 分析工具。

    统计代码变更的基本信息（增删行数、语言、风险标志）。
    """

    # 工具的唯一标识符
    name = "diff_analyzer"

    def run(self, payload: dict, context: ToolContext | None = None) -> ToolResult:
        """执行 diff 分析。

        参数 payload：
            - files: 文件列表，每个文件包含 path（路径）和 diff（变更内容）

        返回：
            ToolResult，包含统计摘要（summary）
        """
        files = payload.get("files", [])  # 获取文件列表
        added_lines = 0  # 新增行数计数器
        deleted_lines = 0  # 删除行数计数器
        languages: set[str] = set()  # 涉及的编程语言（用 set 去重）

        # 遍历每个文件
        for file in files:
            diff = file.get("diff", "")
            # 统计新增行：以 + 开头但不是 +++ 的行（+++ 是 diff 的文件头）
            added_lines += sum(
                1
                for line in diff.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
            # 统计删除行：以 - 开头但不是 --- 的行（--- 是 diff 的文件头）
            deleted_lines += sum(
                1
                for line in diff.splitlines()
                if line.startswith("-") and not line.startswith("---")
            )
            # 从文件扩展名推断编程语言
            path = file.get("path", "")
            if "." in path:
                languages.add(
                    path.rsplit(".", 1)[-1].lower()
                )  # 取最后一个 . 后面的扩展名

        # 构建统计摘要
        summary = {
            "total_files": len(files),  # 总文件数
            "paths": [f.get("path") for f in files],  # 文件路径列表
            "added_lines": added_lines,  # 新增行数
            "deleted_lines": deleted_lines,  # 删除行数
            "languages": sorted(languages),  # 语言列表（排序后返回）
            # 如果总变更超过 200 行，标记为"大变更"风险
            "riskFlags": ["large_diff"] if added_lines + deleted_lines > 200 else [],
        }

        # 返回分析结果
        return ToolResult(
            name=self.name, payload={"files": files, "findings": [], "summary": summary}
        )
