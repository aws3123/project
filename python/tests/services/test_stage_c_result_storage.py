"""Stage C ResultService storage tests with mocked MinIO client."""

from __future__ import annotations

from unittest.mock import Mock

from config.settings import AppSettings
from repositories.result_repository import InMemoryResultRepository
from schemas.api.result import Recommendation, ReviewResult, RiskBreakdown
from schemas.domain.enums import TaskStatus
from services.result_service import ResultService


def build_result(task_id: str = "task-1") -> ReviewResult:
    return ReviewResult(
        taskId=task_id,
        status=TaskStatus.SUCCEEDED,
        riskScore=10,
        riskBreakdown=[RiskBreakdown(dimension="style", score=10)],
        recommendations=[Recommendation(title="ok", detail="ok")],
        traceId=f"trace-{task_id}",
        mode="SYNC",
        reportUrl="reports/task-1.json",
    )


def test_result_service_persist_report_to_minio(monkeypatch):
    mock_minio = Mock()
    mock_minio.bucket_exists.return_value = True

    monkeypatch.setattr(
        "services.result_service.get_minio_client", lambda settings=None: mock_minio
    )
    monkeypatch.setattr(
        "config.settings.AppSettings",
        lambda: AppSettings(
            minio_endpoint="http://minio:9000",
            minio_bucket="review-reports",
            persistence_backend="sql",
        ),
    )

    service = ResultService(InMemoryResultRepository())
    result = service.save(build_result())

    assert result.reportUrl is not None
    assert "review-reports" in result.reportUrl
    assert mock_minio.put_object.called
