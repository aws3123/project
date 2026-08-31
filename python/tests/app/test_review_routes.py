from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_task_service

client = TestClient(app)


def make_payload() -> dict:
    return {
        "projectId": "p1",
        "repo": "repo",
        "branch": "main",
        "files": [{"path": "a.py", "diff": "+1"}],
        "mode": "SYNC",
        "riskPreferences": {},
        "metadata": {},
    }


def test_sync_review_returns_expected_fields() -> None:
    response = client.post("/ai/review/sync", json=make_payload())
    assert response.status_code == 200
    body = response.json()
    assert "taskId" in body
    assert "riskScore" in body
    assert "riskBreakdown" in body
    assert "recommendations" in body
    assert "reportUrl" in body

    logs_resp = client.get(f"/ai/review/logs/{body['taskId']}")
    assert logs_resp.status_code == 200
    logs = logs_resp.json()
    assert len(logs) == 7
    assert [item["node"] for item in logs] == [
        "diff",
        "classifier",
        "impact",
        "rules",
        "rag",
        "scoring",
        "report",
    ]


def test_sync_review_accepts_backend_payload_and_returns_summary_fields() -> None:
    payload = {
        "projectId": "proj-1",
        "projectName": "Demo",
        "prUrl": "https://example.com/pr/1",
        "diffContent": "DELETE FROM users WHERE id = 1;",
        "mode": "SYNC",
    }

    response = client.post("/ai/review/sync", json=payload, headers={"X-Trace-Id": "trace-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["taskId"]
    assert isinstance(body["riskSummary"], str)
    assert len(body["riskSummary"].strip()) > 0
    assert isinstance(body["details"], list)
    assert body["traceId"] == "trace-1"


def test_sync_review_rejects_invalid_backend_payload_with_422() -> None:
    payload = {
        "projectId": "proj-1",
        "projectName": "Demo",
        "mode": "SYNC",
    }

    response = client.post("/ai/review/sync", json=payload)

    assert response.status_code == 422


def test_sync_then_status_retrieval() -> None:
    sync_resp = client.post("/ai/review/sync", json=make_payload())
    assert sync_resp.status_code == 200
    task_id = sync_resp.json()["taskId"]

    status = client.get(f"/ai/review/tasks/{task_id}")
    assert status.status_code == 404


def test_legacy_business_risk_route_removed() -> None:
    response = client.post("/ai/review/business-risk", json={})
    assert response.status_code == 404


def test_handoff_post_success_and_conflict() -> None:
    sync_resp = client.post("/ai/review/sync", json=make_payload())
    assert sync_resp.status_code == 200
    task_id = sync_resp.json()["taskId"]

    task_service = get_task_service()
    task_service.mark_need_review(task_id)

    handoff_resp = client.post(
        f"/ai/review/handoff/{task_id}",
        json={"decision": "APPROVED", "operator": "tester", "comment": "ok"},
    )
    assert handoff_resp.status_code == 404

    conflict_resp = client.post(
        f"/ai/review/handoff/{task_id}",
        json={"decision": "APPROVED", "operator": "tester"},
    )
    assert conflict_resp.status_code == 404


def test_handoff_post_not_found_and_validation() -> None:
    not_found = client.post(
        "/ai/review/handoff/missing-task",
        json={"decision": "APPROVED", "operator": "tester"},
    )
    assert not_found.status_code == 404

    invalid = client.post(
        "/ai/review/handoff/missing-task",
        json={"decision": "INVALID", "operator": "tester"},
    )
    assert invalid.status_code == 422
