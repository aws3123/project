"""Lifecycle and execution leases for LangGraph checkpoint backends."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from math import ceil
from weakref import WeakValueDictionary

from langgraph.checkpoint.memory import InMemorySaver

from config.settings import AppSettings

logger = logging.getLogger(__name__)


class GraphCheckpointManager:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._saver = (
            InMemorySaver() if settings.graph_checkpoint_backend == "memory" else None
        )
        self._stack: AsyncExitStack | None = None
        self._redis = None
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    @property
    def saver(self):
        if self._saver is None:
            raise RuntimeError(
                "Initialize the LangGraph checkpointer during app startup"
            )
        return self._saver

    async def start(self) -> None:
        if self.settings.graph_checkpoint_backend == "memory":
            if self._saver is None:
                self._saver = InMemorySaver()
            if self.settings.app_env == "prod":
                raise ValueError("Production requires GRAPH_CHECKPOINT_BACKEND=redis")
            return
        if self._stack is not None:
            return
        url = self.settings.graph_checkpoint_redis_url
        if not url:
            raise ValueError(
                "GRAPH_CHECKPOINT_REDIS_URL must point to Redis 8 / Redis Stack"
            )
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        from redis.asyncio import Redis

        stack = AsyncExitStack()
        try:
            saver = await stack.enter_async_context(
                AsyncRedisSaver.from_conn_string(
                    url,
                    ttl={
                        "default_ttl": ceil(
                            self.settings.graph_checkpoint_ttl_seconds / 60
                        ),
                        "refresh_on_read": True,
                    },
                )
            )
            await saver.asetup()
            client = Redis.from_url(url)
            stack.push_async_callback(client.aclose)
            await client.ping()
        except BaseException:
            await stack.aclose()
            raise
        self._stack, self._saver, self._redis = stack, saver, client

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack, self._redis, self._saver = None, None, None
        self._locks.clear()

    @asynccontextmanager
    async def execution_lock(self, thread_id: str):
        """Serialize duplicate deliveries; renew the lease for long reviews."""
        local = self._locks.get(thread_id)
        if local is None:
            local = asyncio.Lock()
            self._locks[thread_id] = local
        async with local:
            if self._redis is None:
                if self.settings.graph_checkpoint_backend != "memory":
                    raise RuntimeError("Redis checkpointer has not been initialized")
                yield
                return
            seconds = self.settings.graph_execution_lease_seconds
            lease = self._redis.lock(
                f"langgraph:lease:{thread_id}",
                timeout=seconds,
                blocking_timeout=self.settings.graph_execution_lock_wait_seconds,
                thread_local=False,
            )
            if not await lease.acquire():
                raise TimeoutError("Another worker owns this graph execution")
            owner = asyncio.current_task()
            lost: list[Exception] = []

            async def renew() -> None:
                try:
                    while True:
                        await asyncio.sleep(seconds / 3)
                        if not await lease.extend(seconds, replace_ttl=True):
                            raise RuntimeError("Graph execution lease expired")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    lost.append(exc)
                    if owner is not None:
                        owner.cancel()

            heartbeat = asyncio.create_task(renew())
            try:
                yield
            finally:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
                try:
                    await lease.release()
                except Exception:
                    logger.warning(
                        "Graph execution lease release failed", exc_info=True
                    )
                if lost:
                    raise TimeoutError(
                        "Graph execution stopped after losing its lease"
                    ) from lost[0]
