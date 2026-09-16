"""AIService tests covering runner delegation.

全链路异步化后，AIService 只依赖注入的 async runner（runner.arun），
不再自行持久化 task/result（改由 Java 后端 + GraphRunner 负责）。
本测试验证 AIService 对 runner 的委托行为。
"""

from __future__ import annotations

from schemas.api.request import ReviewRequest
from schemas.api.result import Recommendation, ReviewResult, RiskBreakdown
from schemas.domain.enums import ReviewMode, TaskStatus
from services.ai_service import AIService


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


async def test_delegates_to_runner_without_event_sink():
    request = build_request()
    expected = build_runner_result(request)

    async def runner(req):
        assert req is request
        return expected

    ai_service = AIService(runner)

    result = await ai_service.run(request)
    assert result is expected


async def test_delegates_to_runner_with_event_sink():
    request = build_request()
    expected = build_runner_result(request)
    sink = lambda e: None  # noqa: E731

    async def runner(req, **kwargs):
        assert kwargs.get("event_sink") is sink
        return expected

    ai_service = AIService(runner)

    result = await ai_service.run(request, sink)
    assert result is expected