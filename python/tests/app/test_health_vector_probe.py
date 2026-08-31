from __future__ import annotations

import time

from app.routers import health as health_router
from config.settings import AppSettings


def test_check_vector_reaches_chromadb(monkeypatch):
    captured: dict[str, str] = {}

    monkeypatch.setattr(health_router, "_run_sync_probe", lambda name, probe, settings: probe())

    def _fake_bootstrap(settings=None):
        captured["path"] = settings.chroma_path
        return object()

    monkeypatch.setattr("repositories.chroma.bootstrap_chromadb", _fake_bootstrap)

    result = health_router._check_vector(
        AppSettings(chroma_path="D:/Chroma")
    )

    assert result.status == "UP"
    assert captured["path"] == "D:/Chroma"


def test_check_vector_skips_when_not_configured(monkeypatch):
    monkeypatch.setattr(health_router, "_run_sync_probe", lambda name, probe, settings: probe())

    result = health_router._check_vector(AppSettings(chroma_path=""))

    assert result.status == "UP"
    assert "not configured" in result.detail


def test_run_sync_probe_returns_without_waiting_for_executor_shutdown(monkeypatch):
    monkeypatch.setattr(health_router, "TIMEOUT_SECONDS", 0.01)

    def _slow_probe():
        time.sleep(0.2)
        return health_router._up("slow")

    started = time.perf_counter()
    result = health_router._run_sync_probe("vector", _slow_probe, AppSettings())
    elapsed = time.perf_counter() - started

    assert result.status == "DOWN"
    assert result.detail == "vector timeout after 0.01s"
    assert elapsed < 0.1
