from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from repositories.base import TaskRepositoryProtocol
from schemas.domain.enums import HandoffDecision, TaskStatus
from schemas.api.request import ReviewRequest
from schemas.domain.task import ReviewTask


class TaskService:
    def __init__(self, repository: TaskRepositoryProtocol) -> None:
        self._repo = repository

    def enqueue(self, request: ReviewRequest) -> ReviewTask:
        task_id = str(request.taskId or uuid4())
        task = ReviewTask(
            id=task_id,
            project_id=request.projectId,
            status=TaskStatus.QUEUED,
            payload=request.model_dump(by_alias=True),
            mode=request.mode,
            trace_id=request.traceId or f"trace-{task_id}",
        )
        return self._repo.save(task)

    def mark_processing(self, task_id: str) -> ReviewTask | None:
        return self._repo.update(task_id, status=TaskStatus.PROCESSING)

    def complete(self, task_id: str) -> ReviewTask | None:
        return self._repo.update(task_id, status=TaskStatus.SUCCEEDED)

    def mark_need_review(self, task_id: str) -> ReviewTask | None:
        return self._repo.update(task_id, status=TaskStatus.NEED_REVIEW)

    def handle_handoff(
        self,
        task_id: str,
        decision: HandoffDecision,
        operator: str,
        comment: str | None = None,
    ) -> ReviewTask | None:
        task = self._repo.get(task_id)
        if not task:
            return None
        if task.status != TaskStatus.NEED_REVIEW:
            raise ValueError(f"Task {task_id} is not awaiting human review")

        handoff_payload = {
            **task.payload,
            "handoff": {
                "decision": decision.value,
                "operator": operator,
                "comment": comment,
                "handledAt": datetime.now(UTC).isoformat(),
            },
        }
        if decision == HandoffDecision.APPROVED:
            return self._repo.update(task_id, status=TaskStatus.SUCCEEDED, payload=handoff_payload)
        return self._repo.update(task_id, status=TaskStatus.FAILED, payload=handoff_payload)

    def fail(self, task_id: str, reason: str) -> ReviewTask | None:
        existing = self._repo.get(task_id)
        if not existing:
            return None
        payload = {
            **existing.payload,
            "errorReason": reason,
            "failedAt": datetime.now(UTC).isoformat(),
        }
        return self._repo.update(task_id, status=TaskStatus.FAILED, payload=payload)

    def get(self, task_id: str) -> ReviewTask | None:
        return self._repo.get(task_id)

    def list_ids(self) -> list[str]:
        return self._repo.list_ids()
