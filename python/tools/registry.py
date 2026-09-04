from __future__ import annotations

from typing import Dict

from tools.base import Tool, ToolContext, ToolResult
from tools.diff_analyzer import DiffAnalyzerTool
from tools.incident_search import IncidentSearchTool
from tools.ast_parser import ASTParserTool
from tools.code_knowledge_graph import CodeKnowledgeGraphTool
# 静态检查器（领域单元）从 domain.checkers 引入，仍实现 tools.base.Tool 协议
from domain.checkers.sql_risk_checker import SQLRiskCheckerTool
from domain.checkers.api_breaking_checker import APIBreakingCheckerTool
from domain.checkers.test_coverage_checker import TestCoverageCheckerTool
from domain.checkers.config_change_checker import ConfigChangeCheckerTool


class ToolRegistry:
    def __init__(self) -> None:
        self._registry: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._registry[tool.name] = tool

    def run(self, name: str, payload: dict, context: ToolContext) -> ToolResult:
        if name not in self._registry:
            raise KeyError(f"Tool '{name}' not registered")
        return self._registry[name].run(payload, context)


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(DiffAnalyzerTool())
    registry.register(SQLRiskCheckerTool())
    registry.register(APIBreakingCheckerTool())
    registry.register(IncidentSearchTool())
    registry.register(TestCoverageCheckerTool())
    registry.register(ConfigChangeCheckerTool())
    registry.register(ASTParserTool())
    registry.register(CodeKnowledgeGraphTool())
    return registry
