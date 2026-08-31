from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from schemas.business_risk_source import BusinessRiskSourcePackage


class BusinessRiskReviewRequest(BaseModel):
    run_id: str
    task_id: str
    project_id: str
    repo: str
    branch: str
    request_id: str
    session_id: str | None = None
    trace_id: str | None = None
    source_package: BusinessRiskSourcePackage
    metadata: dict[str, Any] = Field(default_factory=dict)
    memory_context: dict[str, Any] = Field(default_factory=dict)
    user_feedback_signals: dict[str, Any] = Field(default_factory=dict)
    dialog_turn: int | None = None
    memory_version: str | None = None


class BusinessRiskReviewResult(BaseModel):
    run_id: str
    task_id: str
    status: Literal["completed", "failed", "human_review"] = "completed"
    report: dict[str, Any] = Field(default_factory=dict)
    proposed_memory_updates: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
