"""End-to-end test for the business risk pipeline with semantic_hotspot_scan."""

from __future__ import annotations

from unittest.mock import Mock

from app.dependencies import _build_business_risk_runner
from graph.business_risk_runner import BusinessRiskRunner
from repositories.log_repository import InMemoryLogRepository
from schemas.business_risk_review import (
    BusinessRiskReviewRequest,
)
from schemas.business_risk_source import (
    BusinessRiskHotspot,
    BusinessRiskSourceFile,
    BusinessRiskSourcePackage,
)
from services.log_service import LogService
from telemetry.hooks import NoOpTelemetry


def _log_service() -> LogService:
    return LogService(InMemoryLogRepository())


def _mock_llm(return_value: dict):
    llm = Mock()
    llm.chat_structured.return_value = return_value
    return llm


def _request(
    task_id: str, hotspots: list[BusinessRiskHotspot]
) -> BusinessRiskReviewRequest:
    return BusinessRiskReviewRequest(
        run_id=f"run-{task_id}",
        task_id=task_id,
        project_id="p1",
        repo="r",
        branch="main",
        request_id=f"req-{task_id}",
        source_package=BusinessRiskSourcePackage(
            file_count=1,
            files=[
                BusinessRiskSourceFile(
                    path="com/acme/Inventory.java",
                    method_skeletons=[],
                    hotspots=hotspots,
                )
            ],
        ),
    )


def test_full_pipeline_with_llm_finding():
    runner = _build_business_risk_runner(
        task_service=None,
        log_service=_log_service(),
        telemetry=NoOpTelemetry(),
        llm_client=_mock_llm(
            {
                "has_risk": True,
                "category": "state_change",
                "severity": "high",
                "reason": "无事务边界",
                "evidence": "stock--",
                "suggestion": "@Transactional",
                "confidence": 0.9,
            }
        ),
    )
    br_runner = BusinessRiskRunner(runner)

    request = _request(
        "task-1",
        [
            BusinessRiskHotspot(
                reason="库存扣减", snippet="stock--", start_line=10, end_line=15
            )
        ],
    )
    result = br_runner.run(request)

    assert result.status == "human_review"
    assert result.report["overall_risk_level"] == "high"
    assert len(result.report["semantic_findings"]) == 1
    assert result.report["semantic_findings"][0]["source"] == "llm_semantic"
    assert result.report["semantic_status"] == "READY"
    assert result.proposed_memory_updates["semantic_count"] == 1


def test_full_pipeline_without_llm_still_completes():
    runner = _build_business_risk_runner(
        task_service=None,
        log_service=_log_service(),
        telemetry=NoOpTelemetry(),
        llm_client=None,
    )
    br_runner = BusinessRiskRunner(runner)

    request = _request(
        "task-2",
        [
            BusinessRiskHotspot(
                reason="库存扣减", snippet="stock--", start_line=10, end_line=15
            )
        ],
    )
    result = br_runner.run(request)

    # With hotspots present, the rule-based deep_read_methods node produces
    # method_issues -> assess promotes level to MEDIUM -> need_human_review=True.
    # That is the pre-existing behaviour; we only assert the semantic side degrades cleanly.
    assert result.report["semantic_findings"] == []
    assert result.report["semantic_status"] == "llm_skipped"
    assert result.proposed_memory_updates["semantic_count"] == 0


def test_full_pipeline_with_no_hotspots_completes_cleanly():
    runner = _build_business_risk_runner(
        task_service=None,
        log_service=_log_service(),
        telemetry=NoOpTelemetry(),
        llm_client=_mock_llm({"has_risk": False}),
    )
    br_runner = BusinessRiskRunner(runner)

    request = _request("task-3", [])
    result = br_runner.run(request)

    assert result.status == "completed"
    assert result.report["semantic_findings"] == []
    assert result.report["semantic_status"] == "READY"
    assert result.report["overall_risk_level"] == "low"
