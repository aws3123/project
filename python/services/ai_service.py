from __future__ import annotations

from typing import Callable

from graph.events import EventSink
from schemas.api.request import ReviewRequest
from schemas.api.result import ReviewResult


class AIService:
    def __init__(
        self,
        runner: Callable[..., ReviewResult],
    ) -> None:
        self._runner = runner

    def run(
        self,
        request: ReviewRequest,
        event_sink: EventSink | None = None,
    ) -> ReviewResult:
        """Execute the full LangGraph pipeline and return the result.

        Task and result persistence is handled by the Java backend.
        Only node-level logs are persisted by GraphRunner (via LogService).

        event_sink（可选）：流式模式下由路由层注入的事件接收器，
        经 GraphRunner 在节点边界发出进度事件（SSE 流式审查用）。
        """
        if event_sink is None:
            return self._runner(request)
        return self._runner(request, event_sink=event_sink)
