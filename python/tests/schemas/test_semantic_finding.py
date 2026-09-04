"""Tests for the SemanticFindingSchema Pydantic model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.domain.semantic_finding import SemanticFindingSchema


def test_minimal_valid_payload_has_risk_false():
    payload = {"has_risk": False}
    parsed = SemanticFindingSchema.model_validate(payload)
    assert parsed.has_risk is False
    assert parsed.severity == "low"
    assert parsed.confidence == 0.7
    assert parsed.category is None
    assert parsed.reason == ""


def test_full_valid_payload():
    payload = {
        "has_risk": True,
        "category": "state_change",
        "severity": "high",
        "reason": "库存扣减缺少事务边界",
        "evidence": "reserveStock(...)",
        "suggestion": "包裹 @Transactional",
        "confidence": 0.85,
    }
    parsed = SemanticFindingSchema.model_validate(payload)
    assert parsed.has_risk is True
    assert parsed.severity == "high"
    assert parsed.confidence == 0.85


def test_invalid_severity_is_rejected():
    with pytest.raises(ValidationError):
        SemanticFindingSchema.model_validate(
            {"has_risk": True, "severity": "catastrophic"}
        )


def test_confidence_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        SemanticFindingSchema.model_validate({"has_risk": True, "confidence": 1.5})
    with pytest.raises(ValidationError):
        SemanticFindingSchema.model_validate({"has_risk": True, "confidence": -0.1})
