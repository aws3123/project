"""Fallback SSE verifier for hosts without Node.js; same contract as sse_reconnect.mjs."""
from __future__ import annotations

import asyncio
import json
import os
import time

import httpx


BASE = os.getenv("TARGET_URL", "http://localhost:8080")
RUN_ID = os.environ["RUN_ID"]
TOTAL = int(os.getenv("SSE_TASKS", "300"))
DISCONNECT_PERCENT = int(os.getenv("SSE_DISCONNECT_PERCENT", "10"))
HEADERS = {os.getenv("API_KEY_HEADER", "X-API-Key"): os.getenv("API_KEY", "dev-key")}


async def task_ids(client: httpx.AsyncClient) -> list[str]:
    ids: list[str] = []
    for page in range(1, 100):
        response = await client.get(
            f"{BASE}/api/review/tasks",
            params={"page": page, "size": 100, "projectId": f"perf-{RUN_ID}"},
            headers=HEADERS,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        ids.extend(item["taskId"] for item in items)
        if not items:
            break
    if len(ids) < TOTAL:
        raise RuntimeError(f"Expected {TOTAL} tasks, found {len(ids)}")
    return ids[:TOTAL]


async def consume(client: httpx.AsyncClient, task_id: str, disconnect: bool) -> dict:
    seen: set[str] = set()
    event_names: set[str] = set()
    last_id = ""
    reconnect_ms: float | None = None

    async def open_stream(reconnect: bool) -> None:
        nonlocal last_id, reconnect_ms
        headers = {**HEADERS, "Accept": "text/event-stream"}
        if last_id:
            headers["Last-Event-ID"] = last_id
        started = time.perf_counter()
        async with client.stream("GET", f"{BASE}/api/review/tasks/{task_id}/stream", headers=headers) as response:
            response.raise_for_status()
            event: dict[str, str] = {}
            async for line in response.aiter_lines():
                if line:
                    key, _, value = line.partition(":")
                    if key:
                        event[key] = value.strip()
                    continue
                if not event.get("id"):
                    event = {}
                    continue
                if reconnect and reconnect_ms is None:
                    reconnect_ms = (time.perf_counter() - started) * 1000
                seen.add(event["id"])
                last_id = event["id"]
                event_names.add(event.get("event", "message"))
                terminal = event.get("event") in {"result", "task_failed"}
                event = {}
                if disconnect or terminal:
                    return

    try:
        await open_stream(False)
    except (httpx.ReadError, httpx.RemoteProtocolError):
        pass
    if disconnect:
        await open_stream(True)
    return {
        "complete": "status" in event_names and bool({"result", "task_failed"} & event_names),
        "disconnected": disconnect,
        "reconnectMs": reconnect_ms,
        "events": len(seen),
    }


async def main() -> None:
    limits = httpx.Limits(max_connections=TOTAL, max_keepalive_connections=TOTAL)
    async with httpx.AsyncClient(timeout=None, limits=limits) as client:
        ids = await task_ids(client)
        interval = max(1, round(100 / DISCONNECT_PERCENT))
        results = await asyncio.gather(*(consume(client, task_id, i % interval == 0) for i, task_id in enumerate(ids)))
    disconnected = [item for item in results if item["disconnected"]]
    complete = sum(1 for item in results if item["complete"])
    reconnects = [item["reconnectMs"] for item in disconnected if item["reconnectMs"] is not None]
    output = {
        "connections": TOTAL,
        "disconnected": len(disconnected),
        "completionRatio": complete / TOTAL,
        "avgReconnectMs": sum(reconnects) / (len(reconnects) or 1),
        "minEvents": min(item["events"] for item in results),
    }
    print(json.dumps(output, ensure_ascii=False))
    if output["completionRatio"] != 1 or len(disconnected) != round(TOTAL * DISCONNECT_PERCENT / 100):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
