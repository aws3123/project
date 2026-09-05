from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SemanticFindingSchema(BaseModel):
    """LLM output for a single hotspot. `has_risk=False` means the hotspot is benign."""

    has_risk: bool
    category: str | None = None
    severity: Literal["high", "medium", "low"] = "low"
    reason: str = ""
    evidence: str = ""
    suggestion: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
