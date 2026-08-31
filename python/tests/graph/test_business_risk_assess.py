"""Tests for assess_business_risk consuming semantic_findings."""

from __future__ import annotations

from unittest.mock import Mock

from graph.nodes.business_risk import assess_business_risk
from graph.state import NodeContext


def _ctx() -> NodeContext:
    return NodeContext(task_id="t1", registry=Mock())


def test_semantic_findings_promote_level_to_high():
    state = {
        "invariant_violations": {"violations": []},
        "method_issues": {"issues": []},
        "data_flow_paths": {"paths": []},
        "semantic_findings": {
            "items": [{"severity": "medium", "source": "llm_semantic"}],
            "status": "READY",
        },
    }
    result = assess_business_risk(state, _ctx())
    assert result["business_risk_report"]["level"] == "HIGH"
    assert "Semantic" in result["business_risk_report"]["summary"]


def test_no_semantic_findings_falls_back_to_rules():
    state = {
        "invariant_violations": {"violations": []},
        "method_issues": {"issues": []},
        "data_flow_paths": {"paths": []},
        "semantic_findings": {"items": [], "status": "READY"},
    }
    result = assess_business_risk(state, _ctx())
    assert result["business_risk_report"]["level"] == "LOW"


def test_missing_semantic_findings_key_is_safe():
    state = {
        "invariant_violations": {"violations": []},
        "method_issues": {"issues": []},
        "data_flow_paths": {"paths": []},
    }
    result = assess_business_risk(state, _ctx())
    assert result["business_risk_report"]["level"] == "LOW"


def test_violations_still_win_over_semantic_for_summary():
    state = {
        "invariant_violations": {"violations": [{"reason": "x"}]},
        "method_issues": {"issues": []},
        "data_flow_paths": {"paths": []},
        "semantic_findings": {"items": [{"severity": "low"}], "status": "READY"},
    }
    result = assess_business_risk(state, _ctx())
    assert result["business_risk_report"]["level"] == "HIGH"
    assert "state-changing flow" in result["business_risk_report"]["summary"]
