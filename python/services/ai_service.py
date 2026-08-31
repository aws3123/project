from __future__ import annotations

from typing import Callable

from schemas.request import ReviewRequest
from schemas.result import ReviewResult


class AIService:
    def __init__(
        self,
        runner: Callable[[ReviewRequest], ReviewResult],
    ) -> None:
        self._runner = runner

    def run(self, request: ReviewRequest) -> ReviewResult:
        """Execute the full LangGraph pipeline and return the result.

        Task and result persistence is handled by the Java backend.
        Only node-level logs are persisted by GraphRunner (via LogService).
        """
        return self._runner(request)
