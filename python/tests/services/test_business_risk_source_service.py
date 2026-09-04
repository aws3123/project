from unittest.mock import Mock

import pytest

from schemas.domain.business_risk_review import BusinessRiskReviewRequest
from services.business_risk_source_service import BusinessRiskSourceService
from services.business_risk_worker_state import BusinessRiskWorkerState


def make_request() -> BusinessRiskReviewRequest:
    return BusinessRiskReviewRequest(
        run_id="run-1",
        task_id="task-1",
        project_id="ticket-demo",
        repo="ticket-service",
        branch="main",
        request_id="req-1",
        session_id="session-task-1",
        trace_id="trace-1",
        source_package={
            "file_count": 0,
            "files": [],
            "budget": {
                "decision": "ACCEPT_AS_IS",
                "raw_total_bytes": 0,
                "prepared_total_bytes": 0,
                "dropped_files": [],
            },
        },
        metadata={},
        memory_context={},
        user_feedback_signals={},
    )


def test_service_tracks_inflight_and_last_error():
    runner = Mock()
    runner.run.side_effect = RuntimeError("llm timeout api_key=super-secret-token")
    state = BusinessRiskWorkerState()
    service = BusinessRiskSourceService(runner, state)

    with pytest.raises(RuntimeError, match="llm timeout"):
        service.run(make_request())

    snapshot = state.snapshot()
    assert snapshot["inflight_count"] == 0
    assert snapshot["last_error"].startswith("llm timeout")
    assert "super-secret-token" not in snapshot["last_error"]
