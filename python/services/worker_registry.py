from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timezone
from typing import Callable

import httpx

from app.utils import safe_detail
from config.settings import AppSettings
from schemas.api.result import BusinessRiskSourceReadinessStatus
from services.business_risk_worker_state import BusinessRiskWorkerState

logger = logging.getLogger(__name__)


class WorkerRegistry:
    def __init__(
        self,
        settings: AppSettings,
        readiness_provider: Callable[[], BusinessRiskSourceReadinessStatus],
        worker_state: BusinessRiskWorkerState,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._readiness_provider = readiness_provider
        self._worker_state = worker_state
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._running = False
        self._instance_id = f"{socket.gethostname()}:{settings.app_port}"
        self._started_at = datetime.now(timezone.utc).isoformat()

    async def send_heartbeat_once(self) -> None:
        readiness = self._readiness_provider()
        snapshot = self._worker_state.snapshot()
        payload = {
            "instance_id": self._instance_id,
            "worker_version": self._settings.business_risk_worker_version,
            "started_at": self._started_at,
            "schema_versions_supported": [item.strip() for item in self._settings.business_risk_schema_versions_supported.split(',') if item.strip()],
            "java_preprocess_versions_supported": [item.strip() for item in self._settings.business_risk_java_preprocess_versions_supported.split(',') if item.strip()],
            "readiness": readiness.overall,
            "inflight_count": snapshot["inflight_count"],
            "max_concurrency": self._settings.business_risk_worker_max_concurrency,
            "last_error": snapshot["last_error"],
        }
        headers = {
            self._settings.business_risk_worker_token_header: self._settings.business_risk_worker_token,
            "X-Trace-Id": f"worker-heartbeat-{self._instance_id}",
        }
        response = await self._client.post(self._settings.business_risk_worker_heartbeat_url, json=payload, headers=headers)
        response.raise_for_status()

    async def heartbeat_loop(self) -> None:
        self._running = True
        while self._running:
            try:
                await self.send_heartbeat_once()
                await asyncio.sleep(self._settings.business_risk_worker_heartbeat_interval_seconds)
            except Exception as exc:
                logger.warning("Heartbeat loop failed for %s: %s", self._instance_id, safe_detail(exc))
                await asyncio.sleep(5)

    async def unregister(self) -> None:
        self._running = False
        await self._client.aclose()
