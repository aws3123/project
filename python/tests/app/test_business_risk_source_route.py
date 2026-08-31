from fastapi.testclient import TestClient

from app.dependencies import get_business_risk_service
from app.main import app
from app.routers import business_risk_source as source_router
from schemas.business_risk_review import BusinessRiskReviewResult
from schemas.result import BusinessRiskSourceReadinessStatus

client = TestClient(app)


def valid_payload() -> dict:
    return {
        "schema_version": "2.0",
        "java_preprocess_version": "2.0",
        "project_id": "ticket",
        "repo": "ticket-core",
        "branch": "main",
        "request_id": "run-1",
        "session_id": "s-1",
        "source_package": {
            "file_count": 1,
            "files": [
                {
                    "path": "OrderService.java",
                    "language": "java",
                    "package_name": "com.acme.ticket",
                    "class_name": "OrderService",
                    "annotations": ["Service"],
                    "method_skeletons": [
                        {
                            "signature": "public void reserve()",
                            "annotations": ["Transactional"],
                            "control_flow_summary": ["if stock > 0", "decrease stock"],
                            "key_calls": ["inventoryRepo.decrease"],
                            "line_map": {"start_line": 10, "end_line": 20},
                        }
                    ],
                    "hotspots": [
                        {
                            "raw_snippet": "inventoryRepo.decrease()",
                            "reason": "stock deduction",
                            "line_map": {"start_line": 14, "end_line": 14},
                        }
                    ],
                }
            ],
            "budget": {
                "decision": "ACCEPT_AS_IS",
                "raw_total_bytes": 120,
                "prepared_total_bytes": 80,
                "dropped_files": [],
            },
        },
        "metadata": {},
        "memory_context": {},
    }


def completed_result(run_id: str, task_id: str, trace_id: str | None) -> BusinessRiskReviewResult:
    return BusinessRiskReviewResult(
        run_id=run_id,
        task_id=task_id,
        status="completed",
        report={
            "overall_risk_level": "medium",
            "executive_summary": "ok",
            "items": [],
        },
        proposed_memory_updates={},
        trace_id=trace_id,
    )


def up_readiness() -> BusinessRiskSourceReadinessStatus:
    return BusinessRiskSourceReadinessStatus(
        overall="UP",
        route={"status": "UP", "detail": "business-risk-source readiness route registered"},
        config={"status": "UP", "detail": "llm_api_key configured"},
        persistence={"status": "UP", "detail": "stateless worker does not require task persistence"},
        llm={"status": "UP", "detail": "llm_api_key configured"},
    )


def test_source_route_is_registered(monkeypatch) -> None:
    class StubService:
        def run(self, request):
            return completed_result(request.run_id, request.task_id, request.trace_id)

    monkeypatch.setattr(source_router, "get_business_risk_source_readiness", up_readiness)
    app.dependency_overrides[get_business_risk_service] = lambda: StubService()
    try:
        response = client.post("/ai/business-risk/source", json=valid_payload())
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
    finally:
        app.dependency_overrides.clear()


def test_source_route_rejects_diff_field() -> None:
    payload = valid_payload()
    payload["diff"] = "forbidden"

    response = client.post("/ai/business-risk/source", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "diff field is not allowed"


def test_source_route_returns_503_when_business_risk_readiness_is_down(monkeypatch) -> None:
    monkeypatch.setattr(
        source_router,
        "get_business_risk_source_readiness",
        lambda: BusinessRiskSourceReadinessStatus(
            overall="DOWN",
            route={"status": "UP", "detail": "business-risk-source readiness route registered"},
            config={"status": "DOWN", "detail": "llm_api_key is required"},
            persistence={"status": "UP", "detail": "stateless worker does not require task persistence"},
            llm={"status": "DOWN", "detail": "llm_api_key is required"},
        ),
    )

    payload = valid_payload()
    payload["request_id"] = "run-readiness-down"
    payload["session_id"] = "s-readiness-down"

    response = client.post("/ai/business-risk/source", json=payload)

    assert response.status_code == 503
    assert response.json()["detail"] == "business-risk source is not ready: llm_api_key is required"


def test_source_route_rejects_over_200_files() -> None:
    payload = valid_payload()
    payload["source_package"] = {
        "file_count": 201,
        "files": [
            {
                "path": f"A{i}.java",
                "language": "java",
                "method_skeletons": [],
                "hotspots": [],
            }
            for i in range(201)
        ],
    }

    response = client.post("/ai/business-risk/source", json=payload)
    assert response.status_code == 422


def test_old_business_risk_route_removed() -> None:
    response = client.post("/ai/review/business-risk", json={})
    assert response.status_code == 404


def test_source_route_accepts_legacy_source_bundle_alias(monkeypatch) -> None:
    class StubService:
        def run(self, request):
            return completed_result(request.run_id, request.task_id, request.trace_id)

    monkeypatch.setattr(source_router, "get_business_risk_source_readiness", up_readiness)
    app.dependency_overrides[get_business_risk_service] = lambda: StubService()
    try:
        payload = valid_payload()
        payload["source_bundle"] = payload.pop("source_package")
        response = client.post("/ai/business-risk/source", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
    finally:
        app.dependency_overrides.clear()


def test_source_route_uses_request_trace_id_in_response(monkeypatch) -> None:
    class StubService:
        def run(self, request):
            return completed_result(request.run_id, request.task_id, request.trace_id or "missing")

    monkeypatch.setattr(source_router, "get_business_risk_source_readiness", up_readiness)
    app.dependency_overrides[get_business_risk_service] = lambda: StubService()
    try:
        payload = valid_payload()
        payload["request_id"] = "run-trace-req-1"
        payload["session_id"] = "s-trace-req-1"
        payload["trace_id"] = "trace-p2-1"
        response = client.post("/ai/business-risk/source", json=payload)
        assert response.status_code == 200
        assert response.json()["trace_id"] == "trace-p2-1"
    finally:
        app.dependency_overrides.clear()


def test_source_route_falls_back_to_header_trace_id(monkeypatch) -> None:
    class StubService:
        def run(self, request):
            return completed_result(request.run_id, request.task_id, request.trace_id or "missing")

    monkeypatch.setattr(source_router, "get_business_risk_source_readiness", up_readiness)
    app.dependency_overrides[get_business_risk_service] = lambda: StubService()
    try:
        payload = valid_payload()
        payload["request_id"] = "run-trace-header-1"
        payload["session_id"] = "s-trace-header-1"
        payload.pop("trace_id", None)
        response = client.post(
            "/ai/business-risk/source",
            json=payload,
            headers={"X-Trace-Id": "trace-header-p2-1"},
        )
        assert response.status_code == 200
        assert response.json()["trace_id"] == "trace-header-p2-1"
    finally:
        app.dependency_overrides.clear()


def test_source_route_returns_failed_payload_when_service_raises(monkeypatch) -> None:
    class FailingService:
        def run(self, request):
            raise RuntimeError("network down password=super-secret-token")

    monkeypatch.setattr(source_router, "get_business_risk_source_readiness", up_readiness)
    app.dependency_overrides[get_business_risk_service] = lambda: FailingService()
    try:
        payload = valid_payload()
        response = client.post("/ai/business-risk/source", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "failed"
        assert response.json()["proposed_memory_updates"]["code"] == "BUSINESS_RISK_SOURCE_FAILED"
        assert "super-secret-token" not in response.json()["proposed_memory_updates"]["message"]
        assert response.json()["proposed_memory_updates"]["message"].startswith("network down")
    finally:
        app.dependency_overrides.clear()
