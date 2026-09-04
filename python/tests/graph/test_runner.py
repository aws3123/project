"""Tests for GraphBuilder and GraphRunner orchestration."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from graph.builder import GraphBuilder
from graph.runner import GraphRunner
from graph.state import GraphState, NodeContext
from repositories.log_repository import InMemoryLogRepository
from schemas.domain.enums import ReviewMode, TaskStatus
from schemas.api.request import ReviewRequest
from services.log_service import LogService
from telemetry.hooks import TelemetryHook
from tools.registry import ToolRegistry


def dummy_request() -> ReviewRequest:
    return ReviewRequest(
        projectId="demo",
        repo="git@example/demo.git",
        branch="main",
        files=[],
        mode=ReviewMode.SYNC,
    )


def test_graph_builder_creates_runner():
    registry = ToolRegistry()
    telemetry = Mock(spec=TelemetryHook)
    log_service = LogService(InMemoryLogRepository(), telemetry=telemetry)
    builder = GraphBuilder(registry=registry, log_service=log_service, telemetry=telemetry)

    def node(state: GraphState, ctx: NodeContext) -> GraphState:
        state["summary"] = "ok"
        return state

    runner = builder.add_node("sample", node).build()
    assert isinstance(runner, GraphRunner)
    assert runner.count_nodes() == 1

    request = dummy_request()
    result = runner.run(request)
    assert result.recommendations[0].detail == "ok"
    logs = log_service.list_by_task(str(request.taskId))
    assert len(logs) == 1
    telemetry.record_node.assert_called_once()


def test_builder_requires_nodes():
    registry = ToolRegistry()
    telemetry = Mock(spec=TelemetryHook)
    log_service = LogService(InMemoryLogRepository(), telemetry=telemetry)
    builder = GraphBuilder(registry, log_service, telemetry)
    with pytest.raises(ValueError):
        builder.build()


def test_runner_maps_need_human_review_to_need_review_status():
    registry = ToolRegistry()
    telemetry = Mock(spec=TelemetryHook)
    log_service = LogService(InMemoryLogRepository(), telemetry=telemetry)
    builder = GraphBuilder(registry=registry, log_service=log_service, telemetry=telemetry)

    def risk_node(state: GraphState, ctx: NodeContext) -> GraphState:
        state["need_human_review"] = True
        state["summary"] = "risk detected"
        return state

    runner = builder.add_node("risk", risk_node).build()
    result = runner.run(dummy_request())

    assert result.status == TaskStatus.NEED_REVIEW
    assert result.needHumanReview is True


def test_runner_logs_selector_failure_and_falls_back(caplog):
    registry = ToolRegistry()
    telemetry = Mock(spec=TelemetryHook)
    log_service = LogService(InMemoryLogRepository(), telemetry=telemetry)
    builder = GraphBuilder(
        registry=registry,
        log_service=log_service,
        telemetry=telemetry,
        agent_selector=lambda state: (_ for _ in ()).throw(RuntimeError("selector blew up token=super-secret-token")),
    )

    def first_node(state: GraphState, ctx: NodeContext) -> GraphState:
        state["summary"] = "ok"
        return state

    def second_node(state: GraphState, ctx: NodeContext) -> GraphState:
        state["details"] = ["ran"]
        return state

    runner = builder.add_parallel_group([
        ("first", first_node),
        ("second", second_node),
    ]).build()

    with caplog.at_level("WARNING"):
        state = runner.run_state({"task_id": "task-1", "request": {}})

    assert state["summary"] == "ok"
    assert state["details"] == ["ran"]
    assert "selector blew up" in caplog.text
    assert "super-secret-token" not in caplog.text
