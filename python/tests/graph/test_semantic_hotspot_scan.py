"""Tests for the semantic_hotspot_scan node."""

from __future__ import annotations

from unittest.mock import Mock

from graph.nodes.semantic_hotspot_scan import scan_semantic_hotspots
from graph.state import NodeContext


def _ctx(llm_client=None) -> NodeContext:
    return NodeContext(task_id="t1", registry=Mock(), llm_client=llm_client)


def _state_with_hotspots(hotspots):
    return {
        "task_id": "t1",
        "source_package": {
            "files": [
                {
                    "path": "com/acme/InventoryService.java",
                    "class_summary": "Inventory aggregate",
                    "annotations": ["@Service"],
                    "method_skeletons": [],
                    "hotspots": hotspots,
                }
            ],
        },
    }


def test_disabled_flag_writes_empty_findings():
    state = _state_with_hotspots([{"reason": "r", "snippet": "s", "start_line": 1}])
    import graph.nodes.semantic_hotspot_scan as mod

    original = mod.SETTINGS
    try:
        mod.SETTINGS = type(
            "S",
            (),
            {
                "semantic_hotspot_enabled": False,
                "semantic_hotspot_concurrency": 5,
                "semantic_hotspot_confidence_threshold": 0.6,
            },
        )()
        result = scan_semantic_hotspots(state, _ctx())
    finally:
        mod.SETTINGS = original

    assert result["semantic_findings"] == {
        "items": [],
        "scanned_count": 0,
        "status": "disabled",
        "reason": None,
    }


def test_missing_llm_client_writes_llm_skipped():
    state = _state_with_hotspots([{"reason": "r", "snippet": "s", "start_line": 1}])
    result = scan_semantic_hotspots(state, _ctx(llm_client=None))
    assert result["semantic_findings"]["status"] == "llm_skipped"
    assert result["semantic_findings"]["items"] == []
    assert result["semantic_findings"]["scanned_count"] == 1


def test_no_hotspots_skips_llm_and_returns_ready():
    state = _state_with_hotspots([])
    fake_llm = Mock()
    result = scan_semantic_hotspots(state, _ctx(llm_client=fake_llm))
    assert result["semantic_findings"]["status"] == "READY"
    assert result["semantic_findings"]["items"] == []
    assert result["semantic_findings"]["scanned_count"] == 0
    fake_llm.chat_structured.assert_not_called()


from schemas.semantic_finding import SemanticFindingSchema


def _make_mock_llm(responses: list[dict]):
    """Returns a mock whose chat_structured yields each response in turn."""
    llm = Mock()

    def _side_effect(messages=None, output_schema=None, **kwargs):
        assert output_schema is SemanticFindingSchema
        return next(it)

    it = iter(responses)
    llm.chat_structured.side_effect = _side_effect
    return llm


def test_llm_happy_path_collects_risk_items():
    state = _state_with_hotspots(
        [
            {
                "signature": "deduct()",
                "reason": "库存扣减",
                "snippet": "stock--",
                "start_line": 10,
            },
            {
                "signature": "ping()",
                "reason": "健康检查",
                "snippet": "return ok",
                "start_line": 1,
            },
        ]
    )
    llm = _make_mock_llm(
        [
            {
                "has_risk": True,
                "category": "state_change",
                "severity": "high",
                "reason": "无事务边界",
                "evidence": "stock--",
                "suggestion": "@Transactional",
                "confidence": 0.85,
            },
            {"has_risk": False},
        ]
    )
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    findings = result["semantic_findings"]

    assert findings["status"] == "READY"
    assert findings["scanned_count"] == 2
    assert len(findings["items"]) == 1
    item = findings["items"][0]
    assert item["source"] == "llm_semantic"
    assert item["severity"] == "high"
    assert item["signature"] == "deduct()"
    assert item["path"] == "com/acme/InventoryService.java"


def test_low_confidence_downgrades_severity():
    state = _state_with_hotspots(
        [
            {"signature": "risky()", "reason": "r", "snippet": "s", "start_line": 1},
        ]
    )
    llm = _make_mock_llm(
        [
            {"has_risk": True, "severity": "high", "confidence": 0.4},
        ]
    )
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    assert result["semantic_findings"]["items"][0]["severity"] == "medium"


def test_low_confidence_does_not_downgrade_low():
    state = _state_with_hotspots(
        [
            {"signature": "risky()", "reason": "r", "snippet": "s", "start_line": 1},
        ]
    )
    llm = _make_mock_llm(
        [
            {"has_risk": True, "severity": "low", "confidence": 0.4},
        ]
    )
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    assert result["semantic_findings"]["items"][0]["severity"] == "low"


def test_all_calls_fail_results_in_llm_failed():
    state = _state_with_hotspots(
        [
            {"signature": "a()", "reason": "r", "snippet": "s", "start_line": 1},
            {"signature": "b()", "reason": "r", "snippet": "s", "start_line": 5},
        ]
    )
    llm = Mock()
    llm.chat_structured.side_effect = RuntimeError("boom")
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    findings = result["semantic_findings"]
    assert findings["status"] == "llm_failed"
    assert findings["items"] == []
    assert findings["scanned_count"] == 2
    assert findings["reason"] is not None and "boom" in findings["reason"]


def test_partial_failure_still_returns_ready():
    state = _state_with_hotspots(
        [
            {"signature": "ok()", "reason": "r", "snippet": "s", "start_line": 1},
            {"signature": "bad()", "reason": "r", "snippet": "s", "start_line": 5},
        ]
    )
    llm = Mock()
    llm.chat_structured.side_effect = [
        {"has_risk": True, "severity": "medium", "confidence": 0.9},
        RuntimeError("timeout"),
    ]
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    findings = result["semantic_findings"]
    assert findings["status"] == "READY"
    assert len(findings["items"]) == 1
