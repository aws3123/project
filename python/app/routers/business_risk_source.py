from __future__ import annotations

import json
import logging
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.dependencies import (
    get_business_risk_service,
    get_business_risk_source_readiness,
    get_memory_service,
    get_trace_id,
)
from app.utils import safe_detail
from config.settings import AppSettings
from schemas.api.result import BusinessRiskSourceReadinessStatus
from schemas.domain.business_risk_review import BusinessRiskReviewRequest
from schemas.domain.business_risk_source import BusinessRiskSourceRequest
from schemas.domain.business_risk_source_result import BusinessRiskSourceResponse
from services.memory_service import MemoryService

router = APIRouter()
logger = logging.getLogger(__name__)


def _safe_detail(exc: Exception, settings: AppSettings | None = None) -> str:
    extra_secrets = []
    if settings is not None:
        extra_secrets = [
            settings.llm_api_key,
            settings.minio_secret_key,
            settings.business_risk_worker_token,
        ]
    return safe_detail(exc, extra_secrets=extra_secrets)


def _not_ready_reason(readiness: BusinessRiskSourceReadinessStatus) -> str:
    if readiness.config.status == "DOWN" and readiness.config.detail:
        return readiness.config.detail
    if readiness.llm.status == "DOWN" and readiness.llm.detail:
        return readiness.llm.detail
    return "readiness checks reported DOWN"


def _build_run_id(request: BusinessRiskSourceRequest) -> str:
    if request.request_id:
        return request.request_id
    if request.task_id:
        return request.task_id

    normalized_files = []
    for source_file in request.source_package.files:
        normalized_files.append(
            {
                "path": source_file.path,
                "method_count": len(source_file.method_skeletons),
                "hotspot_count": len(source_file.hotspots),
            }
        )
    normalized_files.sort(key=lambda x: x["path"])

    seed_obj = {
        "project_id": request.project_id,
        "repo": request.repo,
        "branch": request.branch,
        "dialog_turn": request.dialog_turn or 0,
        "memory_version": request.memory_version,
        "files": normalized_files,
        "memory_context": request.memory_context,
        "user_feedback_signals": request.user_feedback_signals,
    }
    run_id_seed = json.dumps(seed_obj, sort_keys=True, ensure_ascii=False)
    return f"business-risk-{sha256(run_id_seed.encode('utf-8')).hexdigest()[:16]}"


def _to_business_risk_request(
    request: BusinessRiskSourceRequest, trace_id: str
) -> BusinessRiskReviewRequest:
    run_id = _build_run_id(request)
    task_id = request.task_id or run_id
    request_id = request.request_id or run_id
    metadata = request.metadata if isinstance(request.metadata, dict) else {}

    return BusinessRiskReviewRequest(
        run_id=run_id,
        task_id=task_id,
        project_id=request.project_id,
        repo=request.repo,
        branch=request.branch,
        request_id=request_id,
        session_id=request.session_id,
        trace_id=request.trace_id or trace_id,
        source_package=request.source_package,
        metadata=metadata,
        memory_context=request.memory_context,
        memory_version=request.memory_version,
        dialog_turn=request.dialog_turn,
        user_feedback_signals=request.user_feedback_signals,
    )


@router.post("/business-risk/source", response_model=BusinessRiskSourceResponse)
async def analyze_source_business_risk(
    payload: dict,
    ai_service=Depends(get_business_risk_service),
    memory_service: MemoryService = Depends(get_memory_service),
    trace_id: str = Depends(get_trace_id),
):
    settings = AppSettings()
    readiness = get_business_risk_source_readiness()
    if readiness.overall != "UP":
        reason = _not_ready_reason(readiness)
        raise HTTPException(
            status_code=503,
            detail=f"business-risk source is not ready: {reason}",
        )

    if "diff" in payload:
        raise HTTPException(status_code=422, detail="diff field is not allowed")

    try:
        request = BusinessRiskSourceRequest(**payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_context=False),
        ) from exc

    # P2: Load session memory from Redis before processing
    loaded_memory = memory_service.load_session_memory(request.session_id)
    if loaded_memory:
        logger.info(
            "Loaded session memory for session_id=%s, merging into request",
            request.session_id,
        )
        merged = dict(request.memory_context or {})
        merged.update(loaded_memory)
        request.memory_context = merged

    review_request = _to_business_risk_request(request, trace_id)
    resolved_trace_id = review_request.trace_id or trace_id

    try:
        result = ai_service.run(review_request)

        # P3: Persist proposed memory updates to Redis after successful processing
        memory_service.save_session_memory(
            request.session_id,
            result.proposed_memory_updates,
            version=request.memory_version,
        )

        return BusinessRiskSourceResponse(
            run_id=result.run_id,
            task_id=result.task_id,
            status=result.status,
            report=result.report,
            proposed_memory_updates=result.proposed_memory_updates,
            trace_id=result.trace_id or resolved_trace_id,
        )
    except Exception as exc:
        logger.exception(
            "business-risk source analysis failed run_id=%s", review_request.run_id
        )

        # P3: Persist error memory updates on failure too
        error_updates = {
            "code": "BUSINESS_RISK_SOURCE_FAILED",
            "message": _safe_detail(exc, settings),
        }
        memory_service.save_session_memory(
            request.session_id,
            error_updates,
            version=request.memory_version,
        )

        return BusinessRiskSourceResponse(
            run_id=review_request.run_id,
            task_id=review_request.task_id,
            status="failed",
            report={
                "overall_risk_level": "unknown",
                "executive_summary": "Business risk analysis failed",
                "items": [],
            },
            proposed_memory_updates=error_updates,
            trace_id=resolved_trace_id,
        )
