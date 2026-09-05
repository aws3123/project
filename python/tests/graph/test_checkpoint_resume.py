"""Tests for GraphRunner checkpoint-based resume capability."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from graph.builder import GraphBuilder
from graph.state import GraphState, NodeContext
from repositories.log_repository import InMemoryLogRepository
from services.checkpoint_service import CheckpointService
from services.log_service import LogService
from telemetry.hooks import TelemetryHook
from tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# In-memory CheckpointService mock (no Redis needed)
# ---------------------------------------------------------------------------


class InMemoryCheckpointService(CheckpointService):
    """CheckpointService that stores data in a plain dict instead of Redis."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def save(self, task_id: str, checkpoint: dict) -> None:
        import copy

        self._store[task_id] = copy.deepcopy(checkpoint)

    def load(self, task_id: str) -> dict | None:
        import copy

        data = self._store.get(task_id)
        return copy.deepcopy(data) if data else None

    def delete(self, task_id: str) -> None:
        self._store.pop(task_id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_builder(ckpt: InMemoryCheckpointService) -> GraphBuilder:
    registry = ToolRegistry()
    telemetry = Mock(spec=TelemetryHook)
    log_service = LogService(InMemoryLogRepository(), telemetry=telemetry)
    return GraphBuilder(
        registry=registry,
        log_service=log_service,
        telemetry=telemetry,
        checkpoint_service=ckpt,
    )


def _node(name: str, value: str = "ok"):
    """Create a simple node that sets state[name] = value and tracks calls."""

    def _fn(state: GraphState, ctx: NodeContext) -> GraphState:
        state[name] = value
        return state

    return _fn


def _tracked_node(name: str, call_log: list[str], value: str = "done"):
    """Create a node that tracks calls in call_log and sets state[name] = value."""

    def _fn(state: GraphState, ctx: NodeContext) -> GraphState:
        call_log.append(name)
        state[name] = value
        return state

    return _fn


def _failing_node(name: str, error_msg: str = "boom"):
    """Create a node that always raises."""

    def _fn(state: GraphState, ctx: NodeContext) -> GraphState:
        raise RuntimeError(error_msg)

    return _fn


# ---------------------------------------------------------------------------
# Test: Sequential phase checkpoint + resume
# ---------------------------------------------------------------------------


def test_sequential_resume_skips_completed_phases():
    """When a sequential node fails, resume should skip already-completed phases."""

    call_log: list[str] = []

    ckpt = InMemoryCheckpointService()
    builder = _make_builder(ckpt)
    builder.add_node("step_a", _tracked_node("step_a", call_log))
    builder.add_node("step_b", _tracked_node("step_b", call_log))
    builder.add_node("step_c_fail", _failing_node("step_c_fail"))
    runner = builder.build()

    # --- First run: fails at step_c_fail ---
    with pytest.raises(RuntimeError, match="boom"):
        runner.run_state({"task_id": "task-seq-1", "request": {}})

    assert call_log == ["step_a", "step_b"]
    assert ckpt.load("task-seq-1") is not None

    # --- Second run: should resume from step_c_fail ---
    # Replace the failing node with a working tracked node
    builder2 = _make_builder(ckpt)
    builder2.add_node("step_a", _tracked_node("step_a", call_log))
    builder2.add_node("step_b", _tracked_node("step_b", call_log))
    builder2.add_node(
        "step_c_fail", _tracked_node("step_c_fail", call_log)
    )  # now succeeds
    runner2 = builder2.build()

    state = runner2.run_state({"task_id": "task-seq-1", "request": {}})

    # step_a and step_b should NOT be called again (resumed from checkpoint)
    assert call_log == ["step_a", "step_b", "step_c_fail"]
    assert state["step_a"] == "done"
    assert state["step_b"] == "done"
    assert state["step_c_fail"] == "done"

    # Checkpoint should be cleaned up after full success
    assert ckpt.load("task-seq-1") is None


# ---------------------------------------------------------------------------
# Test: Parallel phase checkpoint + resume (partial agent failure)
# ---------------------------------------------------------------------------


def test_parallel_resume_only_reruns_failed_agents():
    """When one agent in a parallel phase fails, resume should only re-run that agent."""

    call_log: list[str] = []

    def tracked_agent(name: str):
        def _fn(state: GraphState, ctx: NodeContext) -> GraphState:
            call_log.append(name)
            state[f"{name}_result"] = "done"
            return state

        return _fn

    def failing_agent(name: str):
        def _fn(state: GraphState, ctx: NodeContext) -> GraphState:
            call_log.append(name)
            raise RuntimeError(f"{name} failed")

        return _fn

    ckpt = InMemoryCheckpointService()

    # --- First run: sequential phase + parallel phase with one failing agent ---
    builder = _make_builder(ckpt)
    builder.add_node("setup", _tracked_node("setup", call_log))
    builder.add_parallel_group(
        [
            ("agent_ok", tracked_agent("agent_ok")),
            ("agent_fail", failing_agent("agent_fail")),
        ]
    )
    runner = builder.build()

    with pytest.raises(RuntimeError, match="agent_fail failed"):
        runner.run_state({"task_id": "task-par-1", "request": {}})

    # agent_ok should have been called, agent_fail too
    assert "agent_ok" in call_log
    assert "agent_fail" in call_log
    assert ckpt.load("task-par-1") is not None

    # --- Second run: replace failing agent with working one ---
    call_log.clear()
    builder2 = _make_builder(ckpt)
    builder2.add_node("setup", _tracked_node("setup", call_log))
    builder2.add_parallel_group(
        [
            ("agent_ok", tracked_agent("agent_ok")),
            ("agent_fail", tracked_agent("agent_fail")),  # now succeeds
        ]
    )
    runner2 = builder2.build()

    state = runner2.run_state({"task_id": "task-par-1", "request": {}})

    # setup should NOT be called again (checkpoint skips it)
    assert "setup" not in call_log
    # agent_ok should NOT be called again (was saved in checkpoint)
    assert "agent_ok" not in call_log
    # Only agent_fail should be re-run
    assert call_log == ["agent_fail"]

    # Final state should have results from both agents
    assert state["agent_ok_result"] == "done"
    assert state["agent_fail_result"] == "done"

    # Checkpoint cleaned up
    assert ckpt.load("task-par-1") is None


# ---------------------------------------------------------------------------
# Test: Full success cleans up checkpoint
# ---------------------------------------------------------------------------


def test_full_success_cleans_up_checkpoint():
    """When the pipeline completes successfully, checkpoint should be deleted."""

    ckpt = InMemoryCheckpointService()
    builder = _make_builder(ckpt)
    builder.add_node("step1", _node("step1"))
    builder.add_node("step2", _node("step2"))
    runner = builder.build()

    state = runner.run_state({"task_id": "task-clean", "request": {}})

    assert state["step1"] == "ok"
    assert state["step2"] == "ok"
    assert ckpt.load("task-clean") is None


# ---------------------------------------------------------------------------
# Test: No checkpoint service → behaves as before (no errors)
# ---------------------------------------------------------------------------


def test_no_checkpoint_service_works_normally():
    """Without a checkpoint_service, the runner should work exactly as before."""

    builder = GraphBuilder(
        registry=ToolRegistry(),
        log_service=LogService(
            InMemoryLogRepository(), telemetry=Mock(spec=TelemetryHook)
        ),
        telemetry=Mock(spec=TelemetryHook),
        # No checkpoint_service
    )
    builder.add_node("step", _node("step"))
    runner = builder.build()

    state = runner.run_state({"task_id": "no-ckpt", "request": {}})
    assert state["step"] == "ok"
