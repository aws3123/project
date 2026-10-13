"""LangGraph execution adapter shared by HTTP, SSE, Kafka and CLI callers."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.utils import safe_detail
from graph.circuit_breaker import CircuitBreaker
from graph.events import (
    EventSink,
    emit_run_error,
    emit_run_finished,
    emit_run_started,
    emit_step_finished,
    emit_step_started,
)
from graph.result_mapper import ReviewResultMapper
from graph.state import GraphState, NodeContext
from schemas.api.request import ReviewRequest
from schemas.api.result import ReviewResult
from schemas.domain.log import NodeLog
from services.log_service import LogService
from services.task_service import TaskService
from telemetry.hooks import TelemetryHook
from telemetry.langfuse_tracing import get_langfuse_tracing, traced_operation
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)
AGENT_EXECUTION_TIMEOUT_SECONDS = 45
NodeFn = Callable[[GraphState, NodeContext], GraphState | Awaitable[GraphState]]
Phase = list[tuple[str, NodeFn]]


@dataclass(slots=True)
class RunnerConfig:
    registry: ToolRegistry
    log_service: LogService
    telemetry: TelemetryHook
    task_service: TaskService | None = None
    llm_client: Any | None = None
    circuit_breaker: CircuitBreaker | None = None
    agent_selector: Callable[[GraphState], list[tuple[str, NodeFn]]] | None = None
    checkpointer: BaseCheckpointSaver | None = None
    checkpoint_lock: Callable[[str], AbstractAsyncContextManager] | None = None
    graph_version: str = "review-v1"
    parallel_failure_mode: Literal["degrade", "raise"] = "degrade"
    rag_retrieval_service: Any | None = None


@dataclass(slots=True)
class GraphRunContext:
    """Dependencies are request scoped and never persisted as graph state."""

    node_context: NodeContext
    event_sink: EventSink | None = None


class GraphRunner:
    """Compile phases into a StateGraph; LangGraph owns all scheduling."""

    def __init__(self, phases: list[Phase], config: RunnerConfig) -> None:
        self._phases = [list(phase) for phase in phases if phase]
        if not self._phases:
            raise ValueError("GraphRunner requires at least one node")
        names = [name for phase in self._phases for name, _ in phase]
        if len(names) != len(set(names)) or any(
            n.startswith("__review_") for n in names
        ):
            raise ValueError("Node names must be unique and not use __review_")
        self._config = config
        self._mapper = ReviewResultMapper()
        topology = [
            [(name, f"{fn.__module__}.{fn.__qualname__}") for name, fn in phase]
            for phase in self._phases
        ]
        self._topology_id = hashlib.sha256(json.dumps(topology).encode()).hexdigest()[
            :16
        ]
        self._graph = self._compile()

    @property
    def graph(self):
        """The actual compiled LangGraph, also available for visualization."""
        return self._graph

    def count_nodes(self) -> int:
        return sum(len(phase) for phase in self._phases)

    def _compile(self):
        builder = StateGraph(GraphState, context_schema=GraphRunContext)
        previous = START
        for index, phase in enumerate(self._phases):
            if len(phase) == 1:
                name, fn = phase[0]
                builder.add_node(name, self._wrap_node(name, fn, parallel=False))
                builder.add_edge(previous, name)
                previous = name
                continue
            selector, join = f"__review_select_{index}", f"__review_join_{index}"
            builder.add_node(selector, self._selector(phase))
            builder.add_edge(previous, selector)
            branches = []
            for name, fn in phase:
                builder.add_node(name, self._wrap_node(name, fn, parallel=True))
                builder.add_edge(selector, name)
                branches.append(name)
            builder.add_node(join, self._join(phase))
            builder.add_edge(branches, join)
            previous = join
        builder.add_edge(previous, END)
        return builder.compile(checkpointer=self._config.checkpointer)

    def _selector(self, phase: Phase):
        def select(state: GraphState) -> dict:
            names = [name for name, _ in phase]
            if self._config.agent_selector is not None:
                try:
                    selected = {
                        name for name, _ in self._config.agent_selector(deepcopy(state))
                    }
                    # Preserve the old empty-selection fallback to all reviewers.
                    names = [name for name in names if name in selected] or names
                except Exception as exc:
                    logger.warning(
                        "Agent selector failed, falling back to full phase: %s",
                        safe_detail(exc),
                    )
            return {"selected_agents": names}

        return select

    @staticmethod
    def _join(phase: Phase):
        def join(state: GraphState) -> dict:
            statuses = state.get("node_status", {})
            if any(statuses.get(n) in {"FAILED", "CIRCUIT_OPEN"} for n, _ in phase):
                return {"force_human_review": True}
            return {}

        return join

    def _wrap_node(self, name: str, fn: NodeFn, *, parallel: bool):
        async def execute(state: GraphState, runtime: Runtime[GraphRunContext]) -> dict:
            ctx, sink = runtime.context.node_context, runtime.context.event_sink
            started, status, update = perf_counter(), "SUCCEEDED", {}
            emit_step_started(sink, ctx.task_id, name)
            cb = self._config.circuit_breaker if parallel else None
            circuit_open = False
            try:
                if parallel and name not in state.get("selected_agents", []):
                    status = "SKIPPED"
                elif cb and cb.is_open(name):
                    circuit_open = True
                    if self._config.parallel_failure_mode == "raise":
                        raise TimeoutError(f"Reviewer {name} circuit is open")
                    status = "CIRCUIT_OPEN"
                else:

                    async def call() -> GraphState:
                        local_state = deepcopy(state)
                        if inspect.iscoroutinefunction(fn):
                            return await fn(local_state, ctx)
                        value = await asyncio.to_thread(fn, local_state, ctx)
                        return await value if inspect.isawaitable(value) else value

                    update = (
                        await asyncio.wait_for(call(), AGENT_EXECUTION_TIMEOUT_SECONDS)
                        if parallel
                        else await call()
                    )
                    if not isinstance(update, dict):
                        raise TypeError(f"Node {name} must return a state update dict")
                    if cb:
                        cb.record_success(name)
                self._append_log(name, ctx.task_id, state, update, started, status)
            except asyncio.CancelledError:
                status = "CANCELLED"
                raise
            except Exception as exc:
                status = "FAILED"
                if cb and not circuit_open:
                    cb.record_failure(name)
                error = {"error": safe_detail(exc)}
                self._append_log(name, ctx.task_id, {}, error, started, status)
                if not parallel or self._config.parallel_failure_mode == "raise":
                    raise
                logger.warning("Reviewer %s degraded: %s", name, safe_detail(exc))
                update = {"tool_logs": [{"node": name, "status": "failed", **error}]}
            finally:
                # The Java/frontend SSE contract only accepts these two values.
                wire_status = (
                    "SUCCEEDED" if status in {"SUCCEEDED", "SKIPPED"} else "FAILED"
                )
                emit_step_finished(
                    sink,
                    ctx.task_id,
                    name,
                    wire_status,
                    int((perf_counter() - started) * 1000),
                )
            return {**update, "node_status": {name: status}}

        return traced_operation(f"node.{name}")(execute)

    def _append_log(self, name, task_id, node_input, output, started, status):
        self._config.log_service.append(
            NodeLog(
                task_id=task_id,
                node=name,
                input=dict(node_input),
                output=dict(output),
                duration_ms=int((perf_counter() - started) * 1000),
                status=status,
                timestamp=datetime.now(UTC),
            )
        )

    async def arun(
        self, request: ReviewRequest, event_sink: EventSink | None = None
    ) -> ReviewResult:
        task_id = str(request.taskId)
        trace_metadata = {
            "task_id": task_id,
            "java_trace_id": request.traceId or "",
            "project_id": request.projectId,
            "mode": request.mode.value,
            "graph_version": self._config.graph_version,
            "file_count": len(request.files),
            "react": request.react,
        }
        with get_langfuse_tracing().observation(
            "review",
            kind="chain",
            metadata=trace_metadata,
            session_id=request.session_id or task_id,
            input=request.model_dump(mode="json", by_alias=True),
        ) as observation:
            emit_run_started(event_sink, task_id, self.count_nodes())
            try:
                state = await self.arun_state(
                    {
                        "task_id": task_id,
                        "request": request.model_dump(mode="json", by_alias=True),
                    },
                    event_sink=event_sink,
                )
                result = self._mapper.build(request, state)
            except Exception as exc:
                emit_run_error(
                    event_sink, task_id, type(exc).__name__, safe_detail(exc)
                )
                raise
            emit_run_finished(event_sink, task_id, result)
            observation.update(
                output=result.model_dump(mode="json", by_alias=True),
                metadata={
                    **trace_metadata,
                    "status": str(result.status),
                    "risk_score": result.riskScore,
                    "need_human_review": result.needHumanReview,
                },
            )
            return result

    def _execution_config(self, state: GraphState) -> tuple[dict, str]:
        task_id = str(state.get("task_id") or state.get("run_id") or "")
        if not task_id:
            raise ValueError("A task_id or run_id is required for graph execution")
        request = state.get("request", {})
        execution_id = (
            state.get("run_id")
            or request.get("request_id")
            or (request.get("metadata") or {}).get("execution_id")
            or task_id
        )
        identity = json.dumps([task_id, execution_id], ensure_ascii=False)
        thread_id = (
            f"{self._config.graph_version}:{self._topology_id}:"
            f"{hashlib.sha256(identity.encode()).hexdigest()}"
        )
        canonical = deepcopy(dict(state))
        if isinstance(canonical.get("request"), dict):
            canonical["request"].pop("traceId", None)
            canonical["request"].pop("trace_id", None)
            canonical["request"].pop("mode", None)
        canonical.pop("trace_id", None)
        digest = hashlib.sha256(
            json.dumps(
                canonical, sort_keys=True, ensure_ascii=False, default=str
            ).encode()
        ).hexdigest()
        return {"configurable": {"thread_id": thread_id}}, digest

    async def arun_state(
        self, state: GraphState, event_sink: EventSink | None = None
    ) -> GraphState:
        config, digest = self._execution_config(state)
        with get_langfuse_tracing().observation(
            "graph.execute",
            kind="chain",
            input=state,
            metadata={
                "task_id": str(state.get("task_id") or state.get("run_id")),
                "thread_id": config["configurable"]["thread_id"],
                "graph_version": self._config.graph_version,
                "checkpoint_mode": "disabled"
                if self._config.checkpointer is None
                else "new",
            },
        ) as observation:
            ctx = GraphRunContext(
                NodeContext(
                    task_id=str(state.get("task_id") or state.get("run_id")),
                    registry=self._config.registry,
                    task_service=self._config.task_service,
                    telemetry=self._config.telemetry,
                    llm_client=self._config.llm_client,
                    rag_retrieval_service=self._config.rag_retrieval_service,
                ),
                event_sink,
            )
            lock = (
                self._config.checkpoint_lock(config["configurable"]["thread_id"])
                if self._config.checkpoint_lock
                else nullcontext()
            )
            async with lock:
                inputs = {
                    **state,
                    "input_digest": digest,
                    "graph_version": self._config.graph_version,
                }
                if self._config.checkpointer is not None:
                    snapshot = await self._graph.aget_state(config)
                    observation.update(
                        metadata={
                            "checkpoint_mode": "resume"
                            if snapshot.next
                            else "cached"
                            if snapshot.values
                            else "new"
                        }
                    )
                    if snapshot.values:
                        if snapshot.values.get("input_digest") != digest:
                            raise ValueError(
                                "Execution ID already belongs to a different input"
                            )
                        if not snapshot.next:
                            observation.update(output=snapshot.values)
                            return snapshot.values
                        inputs = None  # Resume without re-injecting the original input.
                result = await self._graph.ainvoke(
                    inputs,
                    config=config,
                    context=ctx,
                    durability="sync",
                )
                observation.update(output=result)
                return result

    def run(self, request, event_sink=None) -> ReviewResult:
        return self._sync(self.arun(request, event_sink))

    def run_state(self, state, event_sink=None) -> GraphState:
        return self._sync(self.arun_state(state, event_sink))

    @staticmethod
    def _sync(coroutine):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        coroutine.close()
        raise RuntimeError("Use arun/arun_state inside an active event loop")
