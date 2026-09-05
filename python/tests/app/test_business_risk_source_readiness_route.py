from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import dependencies
from app.routers import health as health_router
from config.settings import AppSettings

app = FastAPI()
app.include_router(health_router.router, prefix="/ai")
client = TestClient(app)


def test_business_risk_source_readiness_returns_503_when_llm_key_missing(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: AppSettings(llm_api_key="   ", persistence_backend="inmemory"),
    )

    response = client.get("/ai/health/business-risk-source")

    assert response.status_code == 503
    body = response.json()
    assert body["overall"] == "DOWN"
    assert body["route"]["status"] == "UP"
    assert body["config"] == {"status": "DOWN", "detail": "llm_api_key is required"}
    assert body["persistence"] == {
        "status": "UP",
        "detail": "stateless worker does not require task persistence",
    }
    assert body["llm"] == {"status": "DOWN", "detail": "llm_api_key is required"}


def test_business_risk_source_readiness_returns_200_when_llm_key_is_ready(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: AppSettings(llm_api_key="test-key", persistence_backend="sql"),
    )

    response = client.get("/ai/health/business-risk-source")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "UP"
    assert body["route"]["status"] == "UP"
    assert body["config"]["status"] == "UP"
    assert body["persistence"] == {
        "status": "UP",
        "detail": "stateless worker does not require task persistence",
    }
    assert body["llm"]["status"] == "UP"
