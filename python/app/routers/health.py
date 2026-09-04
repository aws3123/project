from __future__ import annotations

import asyncio
from queue import Empty, Queue
from threading import Thread
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.dependencies import get_business_risk_source_readiness
from app.utils import safe_detail
from config.settings import AppSettings
from schemas.api.result import (
    BusinessRiskSourceReadinessStatus,
    HealthComponent,
    HealthStatus,
)

router = APIRouter()

TIMEOUT_SECONDS = 3


def get_settings() -> AppSettings:
    return AppSettings()


def _safe_detail(exc: Exception, settings: AppSettings | None = None) -> str:
    extra_secrets = []
    if settings is not None:
        extra_secrets = [
            settings.llm_api_key,
            settings.minio_secret_key,
        ]
    return safe_detail(exc, extra_secrets=extra_secrets)


def _up(detail: str) -> HealthComponent:
    return HealthComponent(status="UP", detail=detail)


def _down(detail: str) -> HealthComponent:
    return HealthComponent(status="DOWN", detail=detail)


def _run_sync_probe(name: str, probe: Callable[[], HealthComponent], settings: AppSettings) -> HealthComponent:
    result_queue: Queue[HealthComponent | Exception] = Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_queue.put(probe())
        except Exception as exc:  # pragma: no cover
            result_queue.put(exc)

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    try:
        result = result_queue.get(timeout=TIMEOUT_SECONDS)
    except Empty:
        return _down(f"{name} timeout after {TIMEOUT_SECONDS}s")

    if isinstance(result, Exception):
        return _down(f"{name} error: {_safe_detail(result, settings)}")
    return result


def _check_mysql(settings: AppSettings) -> HealthComponent:
    def _probe() -> HealthComponent:
        try:
            from repositories.db import get_engine
            from sqlalchemy import text

            engine = get_engine(settings)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return _up("mysql connected")
        except Exception as exc:
            return _down(f"mysql error: {_safe_detail(exc, settings)}")

    return _run_sync_probe("mysql", _probe, settings)


def _check_redis(settings: AppSettings) -> HealthComponent:
    def _probe() -> HealthComponent:
        try:
            from repositories.db import get_redis_client

            client = get_redis_client(settings)
            client.ping()
            return _up("redis pong")
        except Exception as exc:
            return _down(f"redis error: {_safe_detail(exc, settings)}")

    return _run_sync_probe("redis", _probe, settings)


def _check_minio(settings: AppSettings) -> HealthComponent:
    def _probe() -> HealthComponent:
        try:
            from repositories.db import get_minio_client

            client = get_minio_client(settings)
            client.bucket_exists(settings.minio_bucket)
            return _up("minio reachable")
        except Exception as exc:
            return _down(f"minio error: {_safe_detail(exc, settings)}")

    return _run_sync_probe("minio", _probe, settings)


def _check_vector(settings: AppSettings) -> HealthComponent:
    if not settings.chroma_path:
        return _up("chroma not configured, vector probe skipped")

    def _probe() -> HealthComponent:
        try:
            from repositories.chroma import bootstrap_chromadb

            bootstrap_chromadb(settings)
            return _up("chromadb reachable")
        except Exception as exc:
            return _down(f"vector error: {_safe_detail(exc, settings)}")

    return _run_sync_probe("vector", _probe, settings)


def _normalize_base_url(raw: str) -> str:
    return raw.rstrip("/")


def _check_llm(settings: AppSettings) -> HealthComponent:
    base = _normalize_base_url(settings.llm_api_base)

    def _probe() -> HealthComponent:
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                first = client.get(f"{base}/models")
                if first.status_code < 500:
                    return _up(f"llm reachable: {first.status_code}")
                second = client.get(f"{base}/")
                if second.status_code < 500:
                    return _up(f"llm reachable: {second.status_code}")
                return _down(f"llm status error: {first.status_code}/{second.status_code}")
        except Exception as exc:
            return _down(f"llm error: {_safe_detail(exc, settings)}")

    return _run_sync_probe("llm", _probe, settings)


_REQUIRED_COMPONENTS = ["mysql", "redis", "minio", "vector", "llm"]


def _to_component(value: Any) -> HealthComponent:
    if isinstance(value, HealthComponent):
        return value
    if isinstance(value, dict):
        return HealthComponent(**value)
    raise TypeError("Invalid health component payload")


def _to_business_risk_readiness_component(value: Any, default_detail: str) -> dict[str, str | None]:
    if value is None:
        return {"status": "UP", "detail": default_detail}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {
            "status": value.get("status", "UP"),
            "detail": value.get("detail", default_detail),
        }
    raise TypeError("Invalid business risk readiness component payload")


def _to_business_risk_source_readiness_status(value: Any) -> BusinessRiskSourceReadinessStatus:
    if isinstance(value, BusinessRiskSourceReadinessStatus):
        return value
    if isinstance(value, dict):
        route = _to_business_risk_readiness_component(
            value.get("route"),
            "business-risk-source readiness route registered",
        )
        config = _to_business_risk_readiness_component(
            value.get("config"),
            "llm_api_key configured",
        )
        persistence = _to_business_risk_readiness_component(
            value.get("persistence"),
            "persistence backend configured",
        )
        llm = _to_business_risk_readiness_component(
            value.get("llm"),
            "llm_api_key configured",
        )
        overall = value.get("overall")
        if overall is None:
            overall = "UP" if all(
                component["status"] == "UP"
                for component in (route, config, persistence, llm)
            ) else "DOWN"
        return BusinessRiskSourceReadinessStatus(
            overall=overall,
            route=route,
            config=config,
            persistence=persistence,
            llm=llm,
        )
    raise TypeError("Invalid business risk readiness payload")


def _compute_overall(components: dict[str, HealthComponent]) -> str:
    for name in _REQUIRED_COMPONENTS:
        if _to_component(components[name]).status == "DOWN":
            return "DOWN"
    return "UP"


async def _resolve_component(value: Any) -> HealthComponent:
    if asyncio.iscoroutine(value):
        value = await value
    return _to_component(value)


@router.get("/health", response_model=HealthStatus)
async def health_check(settings: AppSettings = Depends(get_settings)):
    components = {
        "mysql": await _resolve_component(_check_mysql(settings)),
        "redis": await _resolve_component(_check_redis(settings)),
        "minio": await _resolve_component(_check_minio(settings)),
        "vector": await _resolve_component(_check_vector(settings)),
        "llm": await _resolve_component(_check_llm(settings)),
    }
    overall = _compute_overall(components)
    payload = HealthStatus(overall=overall, **components).model_dump()
    status_code = 200 if overall == "UP" else 503
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/health/business-risk-source", response_model=BusinessRiskSourceReadinessStatus)
async def business_risk_source_readiness():
    readiness = _to_business_risk_source_readiness_status(get_business_risk_source_readiness())
    payload = readiness.model_dump()
    status_code = 200 if readiness.overall == "UP" else 503
    return JSONResponse(status_code=status_code, content=payload)
