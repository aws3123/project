"""TaskService unit tests."""

from __future__ import annotations

from repositories.task_repository import InMemoryTaskRepository
from schemas.enums import HandoffDecision, ReviewMode, TaskStatus
from schemas.request import ReviewRequest
from services.task_service import TaskService


def build_request() -> ReviewRequest:
    return ReviewRequest(
        projectId="demo",
        repo="git@example.com/demo.git",
        branch="main",
        files=[],
        mode=ReviewMode.SYNC,
    )


def test_enqueue_and_complete_flow():
    repo = InMemoryTaskRepository()
    service = TaskService(repo)
    request = build_request()

    task = service.enqueue(request)
    assert task.status == TaskStatus.QUEUED

    service.mark_processing(task.id)
    assert service.get(task.id).status == TaskStatus.PROCESSING

    service.complete(task.id)
    assert service.get(task.id).status == TaskStatus.SUCCEEDED


def test_fail_records_reason_in_payload():
    repo = InMemoryTaskRepository()
    service = TaskService(repo)
    task = service.enqueue(build_request())

    service.fail(task.id, reason="timeout")
    failed = service.get(task.id)
    assert failed.status == TaskStatus.FAILED
    assert failed.payload["errorReason"] == "timeout"


def test_mark_need_review_updates_task_status():
    repo = InMemoryTaskRepository()
    service = TaskService(repo)
    task = service.enqueue(build_request())

    service.mark_need_review(task.id)
    updated = service.get(task.id)
    assert updated.status == TaskStatus.NEED_REVIEW


def test_handle_handoff_approved_transitions_to_succeeded():
    repo = InMemoryTaskRepository()
    service = TaskService(repo)
    task = service.enqueue(build_request())
    service.mark_need_review(task.id)

    updated = service.handle_handoff(
        task.id,
        decision=HandoffDecision.APPROVED,
        operator="reviewer-1",
        comment="looks good",
    )

    assert updated is not None
    assert updated.status == TaskStatus.SUCCEEDED
    assert updated.payload["handoff"]["decision"] == "APPROVED"


def test_handle_handoff_rejected_transitions_to_failed():
    repo = InMemoryTaskRepository()
    service = TaskService(repo)
    task = service.enqueue(build_request())
    service.mark_need_review(task.id)

    updated = service.handle_handoff(
        task.id,
        decision=HandoffDecision.REJECTED,
        operator="reviewer-2",
    )

    assert updated is not None
    assert updated.status == TaskStatus.FAILED


def test_handle_handoff_raises_when_not_need_review():
    repo = InMemoryTaskRepository()
    service = TaskService(repo)
    task = service.enqueue(build_request())

    try:
        service.handle_handoff(
            task.id,
            decision=HandoffDecision.APPROVED,
            operator="reviewer-3",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "not awaiting human review" in str(exc)
