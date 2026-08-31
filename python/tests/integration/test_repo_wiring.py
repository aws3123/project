"""Integration tests ensuring repositories and services share state."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_task_service
from mq.bus import get_queue


def test_sync_flow_persists_task_and_result():
    client = TestClient(app)
    payload = {
        "projectId": "demo",
        "repo": "git@example/demo.git",
        "branch": "main",
        "files": [{"path": "a.py", "diff": "+1"}],
        "mode": "SYNC",
        "riskPreferences": {},
        "metadata": {},
    }

    response = client.post("/ai/review/sync", json=payload)
    assert response.status_code == 200
    body = response.json()
    task_id = body["taskId"]

    status = client.get(f"/ai/review/tasks/{task_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["task"]["status"] == "SUCCEEDED"
    assert data["result"]["taskId"] == task_id


def test_async_handoff_flow_closes_need_review_task():
    client = TestClient(app)
    payload = {
        "projectId": "demo",
        "repo": "git@example/demo.git",
        "branch": "main",
        "files": [{"path": "a.py", "diff": "+1"}],
        "mode": "ASYNC",
        "riskPreferences": {},
        "metadata": {},
    }

    enqueue = client.post("/ai/review/async", json=payload)
    assert enqueue.status_code == 200
    task_id = enqueue.json()["taskId"]

    queue = get_queue()
    message = queue.consume()
    assert message is not None

    task_service = get_task_service()
    task_service.mark_need_review(task_id)

    handoff = client.post(
        f"/ai/review/handoff/{task_id}",
        json={"decision": "APPROVED", "operator": "integration"},
    )
    assert handoff.status_code == 200

    status = client.get(f"/ai/review/tasks/{task_id}")
    assert status.status_code == 200
    assert status.json()["task"]["status"] == "SUCCEEDED"
