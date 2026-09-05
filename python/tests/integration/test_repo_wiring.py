"""Integration tests ensuring repositories and services share state."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


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


# NOTE: async handoff flow (enqueue -> consume -> mark_need_review -> handoff)
# was covered by test_async_handoff_flow_closes_need_review_task, removed after
# mq.bus in-memory queue was replaced by the Kafka consumer (mq/review_consumer.py).
# Re-introduce with a Kafka test harness when needed.
