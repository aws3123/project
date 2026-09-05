"""Regression tests for structured rule tool outputs."""

from __future__ import annotations

from domain.checkers.api_breaking_checker import APIBreakingCheckerTool
from domain.checkers.config_change_checker import ConfigChangeCheckerTool
from domain.checkers.sql_risk_checker import SQLRiskCheckerTool
from domain.checkers.test_coverage_checker import (
    TestCoverageCheckerTool as CoverageCheckerTool,
)
from tools.base import ToolContext
from tools.diff_analyzer import DiffAnalyzerTool


def make_context(task_id: str = "task-1") -> ToolContext:
    return ToolContext(task_id=task_id)


def test_diff_analyzer_returns_structured_summary() -> None:
    tool = DiffAnalyzerTool()
    result = tool.run(
        {"files": [{"path": "src/App.tsx", "diff": "+const a = 1\n-old"}]},
        make_context(),
    )

    assert result.payload["findings"] == []
    assert result.payload["summary"]["total_files"] == 1
    assert result.payload["summary"]["added_lines"] == 1
    assert result.payload["summary"]["deleted_lines"] == 1
    assert result.payload["summary"]["languages"] == ["tsx"]
    assert result.payload["summary"]["riskFlags"] == []


def test_diff_analyzer_marks_large_diff_risk_flag() -> None:
    tool = DiffAnalyzerTool()
    diff = "\n".join(f"+line {index}" for index in range(201))

    result = tool.run(
        {"files": [{"path": "src/bulk_change.py", "diff": diff}]},
        make_context(),
    )

    assert result.payload["summary"]["added_lines"] == 201
    assert result.payload["summary"]["deleted_lines"] == 0
    assert result.payload["summary"]["languages"] == ["py"]
    assert result.payload["summary"]["riskFlags"] == ["large_diff"]


def test_sql_risk_checker_returns_structured_high_risk_finding() -> None:
    tool = SQLRiskCheckerTool()
    result = tool.run(
        {"files": [{"path": "db/migration.sql", "diff": "DELETE FROM users;"}]},
        make_context(),
    )

    finding = result.payload["findings"][0]
    assert finding == {
        "severity": "HIGH",
        "category": "sql",
        "title": "Potential destructive query",
        "detail": "Potential destructive query in db/migration.sql",
        "file": "db/migration.sql",
        "line": 1,
        "evidence": "DELETE FROM users;",
        "suggestion": "Add WHERE guard or convert to soft delete",
        "confidence": 0.95,
    }


def test_api_breaking_checker_returns_structured_finding() -> None:
    tool = APIBreakingCheckerTool()
    result = tool.run(
        {
            "files": [
                {
                    "path": "api/user_controller.java",
                    "diff": "@Deprecated\npublic String user()",
                }
            ]
        },
        make_context(),
    )

    finding = result.payload["findings"][0]
    assert finding == {
        "severity": "MEDIUM",
        "category": "api",
        "title": "Potential API contract drift",
        "detail": "Deprecated API usage in api/user_controller.java",
        "file": "api/user_controller.java",
        "line": 1,
        "evidence": "@Deprecated",
        "suggestion": "Review compatibility impact and provide a migration path",
        "confidence": 0.85,
    }


def test_config_change_checker_returns_structured_finding() -> None:
    tool = ConfigChangeCheckerTool()
    result = tool.run(
        {"files": [{"path": "config/application.yml", "diff": "timeout: 100"}]},
        make_context(),
    )

    finding = result.payload["findings"][0]
    assert finding == {
        "severity": "MEDIUM",
        "category": "config",
        "title": "Configuration changed",
        "detail": "Config modified: config/application.yml",
        "file": "config/application.yml",
        "line": 1,
        "evidence": "timeout: 100",
        "suggestion": "Validate rollout impact and confirm safe default values",
        "confidence": 0.8,
    }


def test_test_coverage_checker_returns_structured_finding() -> None:
    tool = CoverageCheckerTool()
    result = tool.run({"coverage": 0.5}, make_context())

    finding = result.payload["findings"][0]
    assert result.payload["coverage"] == 0.5
    assert finding == {
        "severity": "LOW",
        "category": "test",
        "title": "Coverage below target",
        "detail": "Coverage below target: 50%",
        "file": None,
        "line": None,
        "evidence": "coverage=50%",
        "suggestion": "Add tests for changed paths and critical branches",
        "confidence": 0.9,
    }
