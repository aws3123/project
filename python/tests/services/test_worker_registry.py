import pytest

from config.settings import AppSettings
from schemas.api.result import (
    BusinessRiskReadinessComponent,
    BusinessRiskSourceReadinessStatus,
)
from services.business_risk_worker_state import BusinessRiskWorkerState
from services.worker_registry import WorkerRegistry


class StubResponse:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"bad status: {self.status_code}")


class StubClient:
    def __init__(self) -> None:
        self.calls = []

    async def post(self, url, json, headers):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return StubResponse(202)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_registry_posts_java_heartbeat_contract():
    client = StubClient()
    settings = AppSettings(
        llm_api_key="test-key",
        business_risk_worker_heartbeat_url="http://localhost:8080/api/internal/business-risk/worker-heartbeat",
        business_risk_worker_token="dev-callback",
        business_risk_worker_token_header="X-Worker-Token",
        business_risk_worker_version="2026.05.30",
        business_risk_worker_max_concurrency=4,
        business_risk_worker_heartbeat_interval_seconds=15,
        business_risk_schema_versions_supported="2.0,3.0",
        business_risk_java_preprocess_versions_supported="3.0",
    )
    state = BusinessRiskWorkerState()

    registry = WorkerRegistry(
        settings=settings,
        readiness_provider=lambda: BusinessRiskSourceReadinessStatus(
            overall="UP",
            route=BusinessRiskReadinessComponent(
                status="UP", detail="business-risk-source readiness route registered"
            ),
            config=BusinessRiskReadinessComponent(
                status="UP", detail="llm_api_key configured"
            ),
            persistence=BusinessRiskReadinessComponent(
                status="UP", detail="stateless worker does not require task persistence"
            ),
            llm=BusinessRiskReadinessComponent(
                status="UP", detail="llm_api_key configured"
            ),
        ),
        worker_state=state,
        client=client,
    )

    await registry.send_heartbeat_once()

    call = client.calls[0]
    assert (
        call["url"]
        == "http://localhost:8080/api/internal/business-risk/worker-heartbeat"
    )
    assert call["headers"]["X-Worker-Token"] == "dev-callback"
    assert call["json"]["readiness"] == "UP"
    assert call["json"]["inflight_count"] == 0
    assert call["json"]["schema_versions_supported"] == ["2.0", "3.0"]
    assert call["json"]["java_preprocess_versions_supported"] == ["3.0"]


@pytest.mark.asyncio
async def test_registry_logs_heartbeat_failures_and_keeps_retrying(monkeypatch, caplog):
    client = StubClient()
    settings = AppSettings(
        llm_api_key="test-key",
        business_risk_worker_heartbeat_url="http://localhost:8080/api/internal/business-risk/worker-heartbeat",
        business_risk_worker_token="dev-callback",
        business_risk_worker_token_header="X-Worker-Token",
        business_risk_worker_version="2026.05.30",
        business_risk_worker_max_concurrency=4,
        business_risk_worker_heartbeat_interval_seconds=15,
        business_risk_schema_versions_supported="2.0,3.0",
        business_risk_java_preprocess_versions_supported="3.0",
    )
    state = BusinessRiskWorkerState()
    registry = WorkerRegistry(
        settings=settings,
        readiness_provider=lambda: BusinessRiskSourceReadinessStatus(
            overall="UP",
            route=BusinessRiskReadinessComponent(
                status="UP", detail="business-risk-source readiness route registered"
            ),
            config=BusinessRiskReadinessComponent(
                status="UP", detail="llm_api_key configured"
            ),
            persistence=BusinessRiskReadinessComponent(
                status="UP", detail="stateless worker does not require task persistence"
            ),
            llm=BusinessRiskReadinessComponent(
                status="UP", detail="llm_api_key configured"
            ),
        ),
        worker_state=state,
        client=client,
    )

    async def _fail_once():
        registry._running = False
        raise RuntimeError("heartbeat failed token=super-secret-token")

    sleep_calls = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        registry._running = False

    monkeypatch.setattr(registry, "send_heartbeat_once", _fail_once)
    monkeypatch.setattr("services.worker_registry.asyncio.sleep", _fake_sleep)

    with caplog.at_level("WARNING"):
        await registry.heartbeat_loop()

    assert sleep_calls == [5]
    assert "heartbeat failed" in caplog.text
    assert "super-secret-token" not in caplog.text
