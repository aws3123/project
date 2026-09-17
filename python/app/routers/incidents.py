"""人工批准后的反馈事故记录入库端点。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_settings
from repositories.chroma import upsert_unified_chunks
from repositories.es_client import index_unified_chunks
from scripts.ingest_mixed_docs import _classify_risk_type, generate_embeddings

logger = logging.getLogger(__name__)
router = APIRouter()


class ApprovedIncidentDraft(BaseModel):
    draftId: int = Field(gt=0)
    feedbackId: int | None = None
    taskId: str
    incidentContent: str = Field(min_length=1)
    feedbackSnapshotJson: str = "{}"
    astSnapshotJson: str = "{}"
    reviewSnapshotJson: str = "{}"


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _ingest(draft: ApprovedIncidentDraft, settings) -> None:
    ast = _parse_json(draft.astSnapshotJson)
    feedback = _parse_json(draft.feedbackSnapshotJson)
    review = _parse_json(draft.reviewSnapshotJson)
    diff = str(ast.get("diffContent") or "")
    category = str(feedback.get("category") or "")
    code_content = diff[:6000]
    content = draft.incidentContent[:16000]
    chunk = {
        "id": f"feedback-incident:{draft.draftId}",
        "nl_description": content,
        "code_content": code_content,
        "embedding": None,
        "ast_metadata": {
            "entity_name": category,
            "entity_kind": "historical_incident",
            "fully_qualified_name": "",
            "language": "",
            "signature": "",
            "parent_class": None,
            "line_start": 0,
            "line_end": 0,
            "ast_status": "approved_feedback",
        },
        "doc_metadata": {
            "source_doc": "approved_feedback_incident",
            "section_title": "历史事故记录",
            "position_in_doc": 0,
            "risk_type": _classify_risk_type(content),
            "image_urls": [],
            "image_texts": [],
            "incident_draft_id": str(draft.draftId),
            "feedback_id": str(draft.feedbackId or ""),
            "task_id": draft.taskId,
            "feedback_category": category,
            "risk_summary": str(review.get("riskSummary") or "")[:1000],
            "chunk_type": "approved_feedback_incident",
        },
    }
    generate_embeddings([chunk], settings)
    upsert_unified_chunks([chunk], settings)
    index_unified_chunks([chunk], settings)


@router.post("/incidents/approved", status_code=201)
async def ingest_approved_incident(
    draft: ApprovedIncidentDraft,
    settings=Depends(get_settings),
):
    """将已审核通过的标准事故记录幂等写入 Chroma 和 Elasticsearch。"""
    try:
        await asyncio.to_thread(_ingest, draft, settings)
    except Exception as exc:
        logger.exception("approved incident ingestion failed draftId=%s", draft.draftId)
        raise HTTPException(status_code=502, detail="Incident knowledge ingestion failed") from exc
    return {"draftId": draft.draftId, "status": "ingested"}
