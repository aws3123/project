"""Tests for parallel execution engine and circuit breaker."""

from __future__ import annotations

import time

from graph.circuit_breaker import CircuitBreaker
from graph.state import GraphState, NodeContext


def _identity(name: str):
    def _fn(state: GraphState, ctx: NodeContext) -> GraphState:
        state[name] = True
        return state

    return _fn


def _slow_factory(delay: float = 0.1):
    def _fn(state: GraphState, ctx: NodeContext) -> GraphState:
        time.sleep(delay)
        state["slow_done"] = True
        return state

    return _fn


# ---- circuit breaker ----


def test_circuit_breaker_closed_initially():
    cb = CircuitBreaker()
    assert not cb.is_open("security")


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2)
    cb.record_failure("security")
    assert not cb.is_open("security")
    cb.record_failure("security")
    assert cb.is_open("security")


def test_circuit_breaker_recovers_after_success():
    cb = CircuitBreaker(failure_threshold=2)
    cb.record_failure("security")
    cb.record_failure("security")
    cb.record_success("security")
    assert not cb.is_open("security")


def test_circuit_breaker_half_open_after_cooldown():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0)
    cb.record_failure("x")
    cb.record_failure("x")
    assert not cb.is_open("x")  # cooldown=0 allows immediate probe
