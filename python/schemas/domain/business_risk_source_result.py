from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BusinessRiskSourceResponse(BaseModel):
    run_id: str
    task_id: str | None = None
    status: str = "completed"
    report: dict[str, Any] = Field(default_factory=dict)
    proposed_memory_updates: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
