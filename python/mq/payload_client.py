from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import AppSettings

logger = logging.getLogger(__name__)


class PayloadNotFoundError(Exception):
    """任务 payload 不存在 —— 属于永久失败，直接进 DEAD_LETTER。"""


class PayloadFetchError(Exception):
    """拉取 payload 时瞬时错误（网络/5xx/超时）—— 可重试。"""


class PayloadClient:
    """回源 Java 内部端点拉取大 payload。

    消息只携带 taskId 等小字段，diffContent / entities / relations 统一从
    GET /api/internal/review/payload/{taskId} 拉取（幂等读，重复拉取无副作用）。
    鉴权复用现有 X-API-Key（与 BffAstClient 一致）。
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()
        self._base_url = self._settings.bff_base_url.rstrip("/")
        self._api_key = self._settings.bff_api_key
        self._client = httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, task_id: str) -> dict[str, Any]:
        headers = {"X-API-Key": self._api_key} if self._api_key else {}
        url = f"{self._base_url}/api/internal/review/payload/{task_id}"
        try:
            resp = await self._client.get(url, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise PayloadFetchError(f"Payload fetch failed for taskId={task_id}: {exc}") from exc

        if resp.status_code == 404:
            raise PayloadNotFoundError(f"Payload not found for taskId={task_id}")
        if resp.status_code in (401, 403):
            raise PayloadFetchError(
                f"Payload fetch unauthorized for taskId={task_id} (HTTP {resp.status_code})"
            )
        if resp.status_code >= 500:
            raise PayloadFetchError(
                f"Payload fetch server error for taskId={task_id} (HTTP {resp.status_code})"
            )
        resp.raise_for_status()
        return resp.json()
