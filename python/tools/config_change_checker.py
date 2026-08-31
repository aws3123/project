"""
配置文件变更检查工具
========================

作用：
    检查代码变更中是否修改了配置文件（如 .yml、.properties、.json 等）。
    配置变更可能影响系统行为，需要提醒开发者注意。

为什么配置变更需要注意？
    配置文件控制着系统的运行参数（数据库连接、超时时间、开关等）。
    错误的配置变更可能导致系统故障，所以需要特别关注。

检查逻辑：
    遍历每个文件的 diff，检查文件扩展名是否为配置文件类型。
    如果是，就报告一个中等严重程度的发现。
"""

# annotations 延迟求值
from __future__ import annotations

# 导入工具基础类型
from tools.base import Tool, ToolContext, ToolResult


class ConfigChangeCheckerTool(Tool):
    """配置文件变更检查工具。

    检查代码变更中是否修改了配置文件。
    """

    # 工具的唯一标识符
    name = "config_change_checker"

    def run(self, payload: dict, context: ToolContext) -> ToolResult:
        """执行配置文件变更检查。

        参数 payload：
            - files: 文件列表，每个文件包含 path（路径）和 diff（变更内容）

        返回：
            ToolResult，包含检查结果列表（findings）
        """
        findings = []  # 存放所有发现的问题

        # 遍历每个文件
        for file in payload.get("files", []):
            path = file.get("path", "")
            # 检查文件扩展名是否为配置文件类型
            if path.endswith((".yml", ".yaml", ".properties", ".toml", ".json")):
                # 获取 diff 中第一个非空行作为证据
                first_line = next((line for line in file.get("diff", "").splitlines() if line.strip()), "")
                findings.append(
                    {
                        "severity": "MEDIUM",           # 严重程度：中等
                        "category": "config",           # 分类：配置相关
                        "title": "Configuration changed",  # 标题：配置已变更
                        "detail": f"Config modified: {path}",  # 详情
                        "file": path,                   # 所在文件
                        "line": 1 if first_line else None,  # 行号（有内容则为 1）
                        "evidence": first_line,         # 证据：第一个非空行
                        "suggestion": "Validate rollout impact and confirm safe default values",  # 建议
                        "confidence": 0.8,              # 置信度：80%
                    }
                )

        # 返回检查结果
        return ToolResult(name=self.name, payload={"findings": findings})
