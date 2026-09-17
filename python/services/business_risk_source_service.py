from __future__ import annotations

from graph.business_risk_runner import BusinessRiskRunner
from schemas.domain.business_risk_review import (
    BusinessRiskReviewRequest,
    BusinessRiskReviewResult,
)
from services.business_risk_worker_state import BusinessRiskWorkerState


class BusinessRiskSourceService:
    def __init__(
        self, runner: BusinessRiskRunner, worker_state: BusinessRiskWorkerState
    ) -> None:
        self._runner = runner
        self._worker_state = worker_state

    def run(self, request: BusinessRiskReviewRequest) -> BusinessRiskReviewResult:
        with self._worker_state.track_run():
            return self._runner.run(request)
