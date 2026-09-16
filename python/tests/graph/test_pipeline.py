"""End-to-end graph pipeline tests using real node wiring."""

from __future__ import annotations

from app.dependencies import _build_graph_runner
from repositories.log_repository import InMemoryLogRepository
from repositories.task_repository import InMemoryTaskRepository
from schemas.api.request import ReviewRequest
from schemas.domain.enums import ReviewMode, TaskStatus
from services.log_service import LogService
from services.task_service import TaskService
from telemetry.hooks import NoOpTelemetry
from tools.registry import build_default_registry

NODE_COUNT = 8  # diff, classifier, impact, rag, [rules, security, performance], scoring, report


def make_request() -> ReviewRequest:
    return ReviewRequest(
        projectId="demo",
        repo="git@example/demo.git",
        branch="main",
        files=[
            {
                "path": "app/controller/user_controller.py",
                "diff": "DELETE FROM users WHERE id = 1\n@Deprecated",
            },
            {
                "path": "config/application.yml",
                "diff": "feature: true",
            },
        ],
        mode=ReviewMode.SYNC,
        riskPreferences={},
        metadata={"service": "review"},
    )


async def test_pipeline_returns_structured_result_and_logs_all_nodes():
    task_service = TaskService(InMemoryTaskRepository())
    log_service = LogService(InMemoryLogRepository(), telemetry=NoOpTelemetry())
    registry = build_default_registry()

    runner = _build_graph_runner(
        task_service=task_service,
        log_service=log_service,
        telemetry=NoOpTelemetry(),
        registry=registry,
    )

    request = make_request()
    result = await runner.arun(request)

    assert result.status == TaskStatus.NEED_REVIEW
    assert result.needHumanReview is True
    assert 0 <= result.riskScore <= 100
    assert len(result.riskBreakdown) == 6
    assert len(result.recommendations) >= 1
    assert result.reportUrl and result.reportUrl.endswith(f"/{result.taskId}.json")

    logs = log_service.list_by_task(result.taskId)
    report_log = next(log for log in logs if log.node == "report")
    assert report_log.output["summary"].startswith("整体风险")
    assert "Potential destructive query" in report_log.output["summary"]
    assert isinstance(report_log.output["details"], list)
    assert 1 <= len(report_log.output["details"]) <= 3
    assert any(detail.startswith("sql: ") for detail in report_log.output["details"])
    assert len(logs) == NODE_COUNT
    log_names = [log.node for log in logs]
    assert log_names[0] == "diff"
    assert log_names[1] == "classifier"
    assert log_names[2] == "impact"
    assert log_names[3] == "rag"
    assert set(log_names[4:7]) == {"rules", "security", "performance"}
    assert log_names[7] == "scoring"
    assert log_names[8] == "report"
    assert all(log.status == "SUCCEEDED" for log in logs)
