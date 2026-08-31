"""Tests for typed ToolRegistry and tools."""

from __future__ import annotations

import pytest

from tools.base import ToolContext
from tools.registry import ToolRegistry, build_default_registry


def make_context(task_id: str = "task-1") -> ToolContext:
    return ToolContext(task_id=task_id)


def test_run_registered_tool_returns_result():
    registry = build_default_registry()
    result = registry.run("diff_analyzer", {"files": []}, make_context())
    assert result.name == "diff_analyzer"
    assert "summary" in result.payload


def test_unregistered_tool_raises():
    registry = ToolRegistry()
    with pytest.raises(KeyError):
        registry.run("unknown", {}, make_context())


def test_sql_risk_checker_detects_delete():
    registry = build_default_registry()
    payload = {"files": [{"path": "db.sql", "diff": "DELETE FROM users"}]}
    result = registry.run("sql_risk_checker", payload, make_context())
    assert result.payload["findings"]
    assert result.payload["findings"][0]["severity"] == "HIGH"
