"""AIService tests covering task/result services wiring."""

from __future__ import annotations

from unittest.mock import Mock

from repositories.result_repository import InMemoryResultRepository
from repositories.task_repository import InMemoryTaskRepository
from schemas.enums import ReviewMode, TaskStatus
from schemas.request import ReviewRequest
from schemas.result import Recommendation, ReviewResult, RiskBreakdown
from services.ai_service import AIService
from services.result_service import ResultService
from services.task_service import TaskService


def build_request() -> ReviewRequest:
    return ReviewRequest(
        projectId="demo",
        repo="git@example.com/demo.git",
        branch="main",
        files=[],
        mode=ReviewMode.SYNC,
    )


def build_runner_result(request: ReviewRequest) -> ReviewResult:
    task_id = str(request.taskId)
    return ReviewResult(
        taskId=task_id,
        status=TaskStatus.SUCCEEDED,
        riskScore=5,
        riskBreakdown=[RiskBreakdown(dimension="style", score=5)],
        recommendations=[Recommendation(title="ok", detail="ok")],
        traceId=request.traceId or f"trace-{task_id}",
        mode=request.mode.value,
    )


def test_run_persists_task_and_result():
    task_repo = InMemoryTaskRepository()
    result_repo = InMemoryResultRepository()
    task_service = TaskService(task_repo)
    result_service = ResultService(result_repo)
    runner = lambda req: build_runner_result(req)
    ai_service = AIService(task_service, result_service, runner)

    request = build_request()
    result = ai_service.run(request)

    assert result.riskScore == 5
    stored_task = task_service.get(result.taskId)
    assert stored_task.status == TaskStatus.SUCCEEDED
    stored_result = result_service.get(result.taskId)
    assert stored_result is not None


def test_run_need_review_marks_need_review_state():
    task_repo = InMemoryTaskRepository()
    result_repo = InMemoryResultRepository()
    task_service = TaskService(task_repo)
    result_service = ResultService(result_repo)

    request = build_request()
    runner_result = build_runner_result(request).model_copy(update={"status": TaskStatus.NEED_REVIEW})
    runner = Mock(return_value=runner_result)
    ai_service = AIService(task_service, result_service, runner)

    result = ai_service.run(request)

    assert result.status == TaskStatus.NEED_REVIEW
    stored_task = task_service.get(str(request.taskId))
    assert stored_task is not None
    assert stored_task.status == TaskStatus.NEED_REVIEW
