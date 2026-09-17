"""Concurrent synchronous SSE stream test with task-stream resume checks."""
from __future__ import annotations

import asyncio
import json
import os

import httpx

BASE = os.getenv("TARGET_URL", "http://127.0.0.1:8080")
TOTAL = int(os.getenv("SSE_TASKS", "300"))
DISCONNECT = int(os.getenv("SSE_DISCONNECT_PERCENT", "10"))
HEADERS = {os.getenv("API_KEY_HEADER", "X-API-Key"): os.getenv("API_KEY", "dev-key")}
BODY = {
    "projectId": "sse-sync-test",
    "projectName": "SSE Sync Test",
    "prUrl": "https://github.com/perf-org/perf-repo/pull/1",
    "diffContent": "class Demo { public void check() { return; } }",
    "mode": "SYNC",
}


def event_from_lines(lines: list[str]) -> dict[str, str]:
    event: dict[str, str] = {}
    for line in lines:
        key, _, value = line.partition(":")
        if key:
            event[key] = value.strip()
    return event


async def stream(client: httpx.AsyncClient, method: str, url: str, *, body: dict | None = None, last_id: str = "", stop_after_first: bool = False) -> tuple[list[dict[str, str]], str]:
    headers = {**HEADERS, "Accept": "text/event-stream"}
    if last_id:
        headers["Last-Event-ID"] = last_id
    events: list[dict[str, str]] = []
    async with client.stream(method, url, headers=headers, json=body) as response:
        response.raise_for_status()
        lines: list[str] = []
        async for line in response.aiter_lines():
            if line:
                lines.append(line)
                continue
            if lines:
                event = event_from_lines(lines)
                lines = []
                if event.get("id"):
                    events.append(event)
                    if stop_after_first:
                        return events, event["id"]
                    if event.get("event") in {"run_finished", "run_error"}:
                        return events, event["id"]
    return events, events[-1].get("id", "") if events else ""


async def one(client: httpx.AsyncClient, index: int) -> dict:
    disconnect = index % max(1, round(100 / DISCONNECT)) == 0
    events, last_id = await stream(client, "POST", f"{BASE}/api/review/sync/stream", body=BODY, stop_after_first=disconnect)
    names = {event.get("event") for event in events}
    if disconnect and "run_finished" not in names and last_id:
        resumed, _ = await stream(client, "GET", f"{BASE}/api/review/tasks/{json.loads(next(event["data"] for event in events if event.get("event") == "run_started"))["taskId"]}/stream", last_id=last_id)
        events.extend(resumed)
        names.update(event.get("event") for event in resumed)
    return {"complete": "run_finished" in names or "run_error" in names, "disconnected": disconnect, "events": len(events)}


async def main() -> None:
    limits = httpx.Limits(max_connections=TOTAL, max_keepalive_connections=TOTAL)
    async with httpx.AsyncClient(timeout=None, limits=limits) as client:
        results = await asyncio.gather(*(one(client, index) for index in range(TOTAL)))
    disconnected = sum(item["disconnected"] for item in results)
    complete = sum(item["complete"] for item in results)
    output = {"connections": TOTAL, "disconnected": disconnected, "completionRatio": complete / TOTAL, "minEvents": min(item["events"] for item in results)}
    print(json.dumps(output, ensure_ascii=False))
    if complete != TOTAL or disconnected != round(TOTAL * DISCONNECT / 100):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
