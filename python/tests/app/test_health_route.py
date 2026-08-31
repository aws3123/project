from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import health as health_router

app = FastAPI()
app.include_router(health_router.router, prefix="/ai")
client = TestClient(app)


def _mock_component(status: str, detail: str = "") -> dict:
    return {"status": status, "detail": detail}


def test_health_returns_200_and_overall_up_when_all_required_components_up(monkeypatch):
    monkeypatch.setattr(health_router, "_check_mysql", lambda settings: _mock_component("UP", "mysql ok"))
    monkeypatch.setattr(health_router, "_check_redis", lambda settings: _mock_component("UP", "redis ok"))
    monkeypatch.setattr(health_router, "_check_minio", lambda settings: _mock_component("UP", "minio ok"))
    monkeypatch.setattr(health_router, "_check_vector", lambda settings: _mock_component("UP", "vector ok"))
    monkeypatch.setattr(health_router, "_check_llm", lambda settings: _mock_component("UP", "llm ok"))

    response = client.get("/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "UP"


def test_health_returns_503_when_mysql_is_down(monkeypatch):
    monkeypatch.setattr(health_router, "_check_mysql", lambda settings: _mock_component("DOWN", "connect timeout"))
    monkeypatch.setattr(health_router, "_check_redis", lambda settings: _mock_component("UP", "redis ok"))
    monkeypatch.setattr(health_router, "_check_minio", lambda settings: _mock_component("UP", "minio ok"))
    monkeypatch.setattr(health_router, "_check_vector", lambda settings: _mock_component("UP", "vector ok"))
    monkeypatch.setattr(health_router, "_check_llm", lambda settings: _mock_component("UP", "llm ok"))

    response = client.get("/ai/health")

    assert response.status_code == 503
    body = response.json()
    assert body["overall"] == "DOWN"
    assert body["mysql"]["status"] == "DOWN"


def test_health_returns_503_when_llm_probe_fails(monkeypatch):
    monkeypatch.setattr(health_router, "_check_mysql", lambda settings: _mock_component("UP", "mysql ok"))
    monkeypatch.setattr(health_router, "_check_redis", lambda settings: _mock_component("UP", "redis ok"))
    monkeypatch.setattr(health_router, "_check_minio", lambda settings: _mock_component("UP", "minio ok"))
    monkeypatch.setattr(health_router, "_check_vector", lambda settings: _mock_component("UP", "vector ok"))
    monkeypatch.setattr(health_router, "_check_llm", lambda settings: _mock_component("DOWN", "llm timeout"))

    response = client.get("/ai/health")

    assert response.status_code == 503
    body = response.json()
    assert body["overall"] == "DOWN"
    assert body["llm"]["status"] == "DOWN"
