from __future__ import annotations

from io import BytesIO

from repositories.base import ResultRepositoryProtocol
from repositories.db import get_minio_client
from schemas.enums import TaskStatus
from schemas.result import Recommendation, ReviewResult, RiskBreakdown


class ResultService:
    def __init__(self, repository: ResultRepositoryProtocol) -> None:
        self._repo = repository

    def build_default_result(self, task_id: str) -> ReviewResult:
        return ReviewResult(
            taskId=task_id,
            status=TaskStatus.SUCCEEDED,
            riskScore=50,
            riskBreakdown=[
                RiskBreakdown(dimension="style", score=10),
                RiskBreakdown(dimension="bug", score=30),
            ],
            recommendations=[
                Recommendation(title="保持现有测试覆盖率", detail="继续维护单测"),
                Recommendation(title="增加集成测试", detail="覆盖核心链路"),
            ],
            reportUrl=f"https://reports.local/{task_id}.json",
            needHumanReview=False,
            ragStatus="NORMAL",
            tier="LLM_ENHANCED",
            traceId=f"trace-{task_id}",
            mode="SYNC",
        )

    def persist_report(self, result: ReviewResult) -> str:
        from config.settings import AppSettings

        settings = AppSettings()
        report_key = f"reports/{result.taskId}.json"
        body = result.model_dump_json(indent=2).encode("utf-8")

        client = get_minio_client(settings)
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)

        client.put_object(
            bucket_name=settings.minio_bucket,
            object_name=report_key,
            data=BytesIO(body),
            length=len(body),
            content_type="application/json",
        )

        return f"{settings.minio_endpoint}/{settings.minio_bucket}/{report_key}"

    def save(self, result: ReviewResult) -> ReviewResult:
        from config.settings import AppSettings

        settings = AppSettings()
        should_persist_report = settings.persistence_backend == "sql" and (
            not result.reportUrl
            or result.reportUrl.startswith("https://reports.local")
            or result.reportUrl.startswith("reports/")
        )
        if should_persist_report:
            result = result.model_copy(update={"reportUrl": self.persist_report(result)})
        return self._repo.save(result)

    def get(self, task_id: str) -> ReviewResult | None:
        return self._repo.get(task_id)
