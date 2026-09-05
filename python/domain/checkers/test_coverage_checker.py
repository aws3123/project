"""
测试覆盖率检查工具
========================

作用：
    检查代码变更的测试覆盖率是否达标。
    如果覆盖率低于 80%，提醒开发者补充测试。

什么是测试覆盖率？
    测试覆盖率衡量的是"有多少代码被测试用例执行到了"。
    例如：100 行代码中有 80 行被测试执行到，覆盖率就是 80%。
    覆盖率太低意味着很多代码没有被测试验证过，可能存在隐藏的 bug。

检查逻辑：
    从输入中获取覆盖率数值，如果低于 80% 就报告一个低严重程度的发现。
"""

# annotations 延迟求值
from __future__ import annotations

# 导入工具基础类型
from tools.base import Tool, ToolContext, ToolResult


class TestCoverageCheckerTool(Tool):
    """测试覆盖率检查工具。

    检查代码变更的测试覆盖率是否达标（>= 80%）。
    """

    # 工具的唯一标识符
    name = "test_coverage_checker"

    def run(self, payload: dict, context: ToolContext) -> ToolResult:
        """执行测试覆盖率检查。

        参数 payload：
            - coverage: 测试覆盖率（0.0 ~ 1.0 之间的小数，如 0.85 表示 85%）

        返回：
            ToolResult，包含检查结果列表（findings）和覆盖率数值
        """
        coverage = payload.get("coverage", 0.0)  # 获取覆盖率，默认为 0
        findings = []  # 存放所有发现的问题

        # 如果覆盖率低于 80%，报告一个问题
        if coverage < 0.8:
            findings.append(
                {
                    "severity": "LOW",  # 严重程度：低
                    "category": "test",  # 分类：测试相关
                    "title": "Coverage below target",  # 标题：覆盖率未达标
                    "detail": f"Coverage below target: {coverage:.0%}",  # 详情（格式化为百分比）
                    "file": None,  # 不针对特定文件
                    "line": None,  # 不针对特定行
                    "evidence": f"coverage={coverage:.0%}",  # 证据：当前覆盖率
                    "suggestion": "Add tests for changed paths and critical branches",  # 建议
                    "confidence": 0.9,  # 置信度：90%
                }
            )

        # 返回检查结果（包含 findings 和覆盖率数值）
        return ToolResult(
            name=self.name, payload={"findings": findings, "coverage": coverage}
        )
