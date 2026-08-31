# Business Risk: Semantic Hotspot Scan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single LLM-powered node `semantic_hotspot_scan` to the business-risk pipeline that reads BFF-prepared AST hotspots, identifies semantic business-state-change risks, and writes findings in the same shape as existing `invariant_violations` so downstream logic is barely touched.

**Architecture:** New sync node `scan_semantic_hotspots` is added to the existing parallel phase alongside `check_invariants` and `deep_read_methods`. It fans out per-hotspot LLM calls through a bounded `ThreadPoolExecutor` (5 workers by default), uses `chat_structured` with a Pydantic schema for robust output, and degrades silently (`llm_skipped` / `llm_failed`) when the client is missing or any call errors — preserving the deterministic pipeline's behaviour.

**Tech Stack:** Python 3.11+, Pydantic v2, `concurrent.futures`, existing `LLMClient.chat_structured` (OpenAI-compatible), pytest, pytest-asyncio not needed (sync).

**Spec:** `docs/superpowers/specs/2026-06-27-business-risk-semantic-hotspot-scan-design.md`

---

## File structure

| Path | Responsibility | Action |
|---|---|---|
| `python/schemas/semantic_finding.py` | Pydantic schema for LLM output | **Create** |
| `python/graph/nodes/semantic_hotspot_scan.py` | LLM node: fan-out, parse, merge | **Create** |
| `python/graph/nodes/__init__.py` | Export `scan_semantic_hotspots` | **Modify** |
| `python/graph/business_risk_state.py` | Add `semantic_findings` to TypedDict | **Modify** |
| `python/graph/nodes/business_risk.py` | Consume `semantic_findings` when computing level/summary | **Modify** |
| `python/graph/business_risk_result.py` | Pass `semantic_findings` through to the result payload | **Modify** |
| `python/graph/runner.py` | Add `semantic_findings` to `MERGE_STRATEGY` | **Modify** (1 line) |
| `python/app/dependencies.py` | Register node in parallel group; import | **Modify** |
| `python/config/settings.py` | Add 3 settings (`semantic_hotspot_*`) | **Modify** |
| `python/tests/graph/test_semantic_hotspot_scan.py` | 7 unit tests for the new node | **Create** |
| `python/tests/graph/test_business_risk_assess.py` | Extend assess tests for semantic count | **Create** |

---

## Task 1 — Pydantic schema `SemanticFindingSchema`

**Files:**
- Create: `python/schemas/semantic_finding.py`
- Test: `python/tests/schemas/test_semantic_finding.py`

> Note: there is no `python/tests/schemas/` directory yet — create it together with an empty `__init__.py`.

- [ ] **Step 1.1 — Write the failing test**

Create `python/tests/schemas/__init__.py` (empty) and `python/tests/schemas/test_semantic_finding.py`:

```python
"""Tests for the SemanticFindingSchema Pydantic model."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.semantic_finding import SemanticFindingSchema


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
        SemanticFindingSchema.model_validate({"has_risk": True, "severity": "catastrophic"})


def test_confidence_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        SemanticFindingSchema.model_validate({"has_risk": True, "confidence": 1.5})
    with pytest.raises(ValidationError):
        SemanticFindingSchema.model_validate({"has_risk": True, "confidence": -0.1})
```

- [ ] **Step 1.2 — Run test to verify it fails**

```
cd python && uv run pytest tests/schemas/test_semantic_finding.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'schemas.semantic_finding'`.

- [ ] **Step 1.3 — Write the schema**

Create `python/schemas/semantic_finding.py`:

```python
"""Pydantic schema for the semantic-hotspot LLM structured output."""
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
```

- [ ] **Step 1.4 — Run test to verify it passes**

```
cd python && uv run pytest tests/schemas/test_semantic_finding.py -v
```

Expected: 4 passed.

- [ ] **Step 1.5 — Commit**

```
git add python/schemas/semantic_finding.py python/tests/schemas/__init__.py python/tests/schemas/test_semantic_finding.py
git commit -m "feat(schema): add SemanticFindingSchema for LLM hotspot output"
```

---

## Task 2 — Settings entries

**Files:**
- Modify: `python/config/settings.py:6-51`

- [ ] **Step 2.1 — Add three settings**

In `python/config/settings.py`, append three lines inside `AppSettings` (right before `model_config`):

```python
    semantic_hotspot_enabled: bool = True
    semantic_hotspot_concurrency: int = 5
    semantic_hotspot_confidence_threshold: float = 0.6
```

The block should read:

```python
    telemetry_backend: Literal["logging", "noop"] = "logging"

    semantic_hotspot_enabled: bool = True
    semantic_hotspot_concurrency: int = 5
    semantic_hotspot_confidence_threshold: float = 0.6

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }
```

- [ ] **Step 2.2 — Smoke-test that the settings load**

```
cd python && uv run python -c "from config.settings import AppSettings; s = AppSettings(); print(s.semantic_hotspot_enabled, s.semantic_hotspot_concurrency, s.semantic_hotspot_confidence_threshold)"
```

Expected output: `True 5 0.6`

- [ ] **Step 2.3 — Commit**

```
git add python/config/settings.py
git commit -m "feat(settings): add semantic_hotspot_* configuration knobs"
```

---

## Task 3 — `semantic_hotspot_scan` node (no-LLM + disabled + empty-hotspots behaviour)

**Files:**
- Create: `python/graph/nodes/semantic_hotspot_scan.py`
- Create: `python/tests/graph/test_semantic_hotspot_scan.py`

We write the node in three iterations (TDD), each expanding behaviour. This first task pins down the three "no LLM call" branches: disabled flag, missing `llm_client`, and zero hotspots.

- [ ] **Step 3.1 — Write failing tests for the three no-call branches**

Create `python/tests/graph/test_semantic_hotspot_scan.py`:

```python
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
    # enabled=False is injected by overriding settings at call time via wrapper — here we
    # exercise the explicit short-circuit path by patching the module-level SETTINGS ref.
    import graph.nodes.semantic_hotspot_scan as mod
    original = mod.SETTINGS
    try:
        mod.SETTINGS = type("S", (), {
            "semantic_hotspot_enabled": False,
            "semantic_hotspot_concurrency": 5,
            "semantic_hotspot_confidence_threshold": 0.6,
        })()
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
```

- [ ] **Step 3.2 — Run tests to verify they fail**

```
cd python && uv run pytest tests/graph/test_semantic_hotspot_scan.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'graph.nodes.semantic_hotspot_scan'`.

- [ ] **Step 3.3 — Write the minimal node**

Create `python/graph/nodes/semantic_hotspot_scan.py`:

```python
"""Semantic hotspot scan — LLM-powered business-state-change detection.

For each BFF-prepared hotspot, ask the LLM whether the snippet contains an
implicit business-state-change risk. Output shape mirrors
`invariant_violations` so downstream consumers can treat them uniformly.

The node is synchronous. Internal fan-out uses a bounded ThreadPoolExecutor.
Degrades silently when the LLM is unavailable or every call fails.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from config.settings import AppSettings
from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError
from schemas.semantic_finding import SemanticFindingSchema

logger = logging.getLogger(__name__)

SETTINGS: AppSettings = AppSettings()

SYSTEM_PROMPT = (
    "你是 Java 业务风险分析师。给定一个 hotspot 方法（BFF 层 AST 预筛出的"可疑代码片段"），"
    "判断它是否包含隐含的业务状态变更风险。"
    "关注：库存/余额/权益/数量等状态的非预期修改、缺少事务边界的状态变更、并发场景下的竞态、"
    "状态机非法转换、跨聚合副作用。"
    "输出 JSON，字段：has_risk(bool), category(str,可选), severity(high/medium/low), "
    "reason(str,中文), evidence(str), suggestion(str,中文), confidence(0-1)。"
    "若无业务风险，返回 has_risk=false。"
)


def _collect_hotspots(state: GraphState) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    source_package = state.get("source_package") or {}
    files = source_package.get("files") or []
    for file in files:
        if not isinstance(file, dict):
            continue
        path = file.get("path", "")
        class_summary = file.get("class_summary")
        file_annotations = file.get("annotations") or []
        key_calls_by_signature: dict[str, list[str]] = {}
        for skeleton in file.get("method_skeletons") or []:
            if isinstance(skeleton, dict):
                sig = skeleton.get("signature") or ""
                key_calls_by_signature[sig] = skeleton.get("key_calls") or []
        for hotspot in file.get("hotspots") or []:
            if not isinstance(hotspot, dict):
                continue
            out.append({
                "path": path,
                "class_summary": class_summary,
                "file_annotations": file_annotations,
                "key_calls_index": key_calls_by_signature,
                "hotspot": hotspot,
            })
    return out


def _build_messages(entry: dict[str, Any]) -> list[dict[str, str]]:
    hotspot = entry["hotspot"]
    signature = hotspot.get("signature") or hotspot.get("method_id") or "unknown"
    reason = hotspot.get("reason") or ""
    snippet = hotspot.get("snippet") or hotspot.get("raw_snippet") or ""
    context_bits = [f"file: {entry['path']}"]
    if entry.get("class_summary"):
        context_bits.append(f"class summary: {entry['class_summary']}")
    if entry.get("file_annotations"):
        context_bits.append(f"file annotations: {', '.join(entry['file_annotations'])}")
    context = "\n".join(context_bits)
    user_content = (
        f"{context}\n\n"
        f"method signature: {signature}\n"
        f"hotspot reason: {reason}\n"
        f"snippet:\n{snippet}\n"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _scan_one(llm_client: Any, entry: dict[str, Any]) -> dict[str, Any] | None:
    """Returns a normalised finding dict, or None when the LLM says has_risk=false."""
    messages = _build_messages(entry)
    parsed = llm_client.chat_structured(
        messages=messages,
        output_schema=SemanticFindingSchema,
        temperature=0.1,
        max_tokens=512,
    )
    if not parsed.get("has_risk"):
        return None
    hotspot = entry["hotspot"]
    severity = parsed.get("severity") or "low"
    confidence = float(parsed.get("confidence") or 0.7)
    if confidence < SETTINGS.semantic_hotspot_confidence_threshold:
        severity = {"high": "medium", "medium": "low"}.get(severity, severity)
    return {
        "path": entry["path"],
        "signature": hotspot.get("signature") or hotspot.get("method_id") or "unknown",
        "category": parsed.get("category") or "semantic_risk",
        "severity": severity,
        "reason": parsed.get("reason") or "",
        "evidence": parsed.get("evidence") or hotspot.get("snippet") or "",
        "suggestion": parsed.get("suggestion") or "",
        "confidence": confidence,
        "source": "llm_semantic",
    }


def scan_semantic_hotspots(state: GraphState, ctx: NodeContext) -> GraphState:
    hotspots = _collect_hotspots(state)

    if not SETTINGS.semantic_hotspot_enabled:
        state["semantic_findings"] = {
            "items": [], "scanned_count": 0, "status": "disabled", "reason": None,
        }
        return state

    if ctx.llm_client is None:
        state["semantic_findings"] = {
            "items": [], "scanned_count": len(hotspots), "status": "llm_skipped", "reason": None,
        }
        return state

    if not hotspots:
        state["semantic_findings"] = {
            "items": [], "scanned_count": 0, "status": "READY", "reason": None,
        }
        return state

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    max_workers = min(SETTINGS.semantic_hotspot_concurrency, len(hotspots))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_entry = {
            pool.submit(_scan_one, ctx.llm_client, entry): entry
            for entry in hotspots
        }
        for future in as_completed(future_to_entry):
            try:
                finding = future.result()
                if finding is not None:
                    items.append(finding)
            except (LLMStructuredOutputError, Exception) as exc:
                logger.warning("semantic_hotspot_scan failed for one hotspot: %s", exc)
                errors.append(str(exc)[:200])

    status = "READY" if items or not errors else "llm_failed"
    if items and errors:
        status = "READY"  # partial success still counts as READY
    state["semantic_findings"] = {
        "items": items,
        "scanned_count": len(hotspots),
        "status": status,
        "reason": errors[-1] if errors else None,
    }
    return state
```

- [ ] **Step 3.4 — Run tests to verify they pass**

```
cd python && uv run pytest tests/graph/test_semantic_hotspot_scan.py -v
```

Expected: 3 passed (`test_disabled_flag_writes_empty_findings`, `test_missing_llm_client_writes_llm_skipped`, `test_no_hotspots_skips_llm_and_returns_ready`).

- [ ] **Step 3.5 — Commit**

```
git add python/graph/nodes/semantic_hotspot_scan.py python/tests/graph/test_semantic_hotspot_scan.py
git commit -m "feat(node): add semantic_hotspot_scan with disabled/skipped/empty short-circuits"
```

---

## Task 4 — LLM happy path, filtering, partial failure

**Files:**
- Modify: `python/tests/graph/test_semantic_hotspot_scan.py` (extend)

- [ ] **Step 4.1 — Add tests for the LLM behaviour**

Append to `python/tests/graph/test_semantic_hotspot_scan.py`:

```python
from schemas.semantic_finding import SemanticFindingSchema


def _make_mock_llm(responses: list[dict]):
    """Returns a mock whose chat_structured yields each response in turn. Raises if exhausted."""
    llm = Mock()
    it = iter(responses)

    def _side_effect(messages=None, output_schema=None, **kwargs):
        assert output_schema is SemanticFindingSchema
        return next(it)

    llm.chat_structured.side_effect = _side_effect
    return llm


def test_llm_happy_path_collects_risk_items():
    state = _state_with_hotspots([
        {"signature": "deduct()", "reason": "库存扣减", "snippet": "stock--", "start_line": 10},
        {"signature": "ping()", "reason": "健康检查", "snippet": "return ok", "start_line": 1},
    ])
    llm = _make_mock_llm([
        {"has_risk": True, "category": "state_change", "severity": "high",
         "reason": "无事务边界", "evidence": "stock--", "suggestion": "@Transactional",
         "confidence": 0.85},
        {"has_risk": False},
    ])
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
    state = _state_with_hotspots([
        {"signature": "risky()", "reason": "r", "snippet": "s", "start_line": 1},
    ])
    llm = _make_mock_llm([
        {"has_risk": True, "severity": "high", "confidence": 0.4},
    ])
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    assert result["semantic_findings"]["items"][0]["severity"] == "medium"


def test_low_confidence_does_not_downgrade_low():
    state = _state_with_hotspots([
        {"signature": "risky()", "reason": "r", "snippet": "s", "start_line": 1},
    ])
    llm = _make_mock_llm([
        {"has_risk": True, "severity": "low", "confidence": 0.4},
    ])
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    assert result["semantic_findings"]["items"][0]["severity"] == "low"


def test_all_calls_fail_results_in_llm_failed():
    state = _state_with_hotspots([
        {"signature": "a()", "reason": "r", "snippet": "s", "start_line": 1},
        {"signature": "b()", "reason": "r", "snippet": "s", "start_line": 5},
    ])
    llm = Mock()
    llm.chat_structured.side_effect = RuntimeError("boom")
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    findings = result["semantic_findings"]
    assert findings["status"] == "llm_failed"
    assert findings["items"] == []
    assert findings["scanned_count"] == 2
    assert findings["reason"] is not None and "boom" in findings["reason"]


def test_partial_failure_still_returns_ready():
    state = _state_with_hotspots([
        {"signature": "ok()", "reason": "r", "snippet": "s", "start_line": 1},
        {"signature": "bad()", "reason": "r", "snippet": "s", "start_line": 5},
    ])
    llm = Mock()
    llm.chat_structured.side_effect = [
        {"has_risk": True, "severity": "medium", "confidence": 0.9},
        RuntimeError("timeout"),
    ]
    result = scan_semantic_hotspots(state, _ctx(llm_client=llm))
    findings = result["semantic_findings"]
    assert findings["status"] == "READY"
    assert len(findings["items"]) == 1
```

- [ ] **Step 4.2 — Run tests**

```
cd python && uv run pytest tests/graph/test_semantic_hotspot_scan.py -v
```

Expected: 8 passed total (3 from Task 3 + 5 new).

- [ ] **Step 4.3 — Commit**

```
git add python/tests/graph/test_semantic_hotspot_scan.py
git commit -m "test(node/semantic): cover LLM happy path, filtering, partial failure"
```

---

## Task 5 — Register node in `__init__.py` and runner `MERGE_STRATEGY`

**Files:**
- Modify: `python/graph/nodes/__init__.py:1-35`
- Modify: `python/graph/runner.py:35-43`

- [ ] **Step 5.1 — Export the new node**

In `python/graph/nodes/__init__.py`, add the import and append to `__all__`:

```python
from .semantic_hotspot_scan import scan_semantic_hotspots
```

The updated `__all__` list:

```python
__all__ = [
    "analyze_diff",
    "classify_changes",
    "analyze_impact",
    "run_rule_checks",
    "run_rag",
    "audit_security",
    "analyze_performance",
    "extract_business_invariants",
    "trace_data_flow",
    "check_invariants",
    "deep_read_methods",
    "assess_business_risk",
    "verify_business_risks",
    "scan_semantic_hotspots",
    "score_risks",
    "summarize",
]
```

- [ ] **Step 5.2 — Add merge strategy entry**

In `python/graph/runner.py`, update `MERGE_STRATEGY`:

```python
MERGE_STRATEGY: dict[str, str] = {
    "tool_logs": "extend",
    "rule_findings": "replace",
    "rag_context": "replace",
    "security_findings": "replace",
    "performance_findings": "replace",
    "semantic_findings": "replace",
    "rag_analysis": "overwrite",
    "rag_status": "overwrite",
}
```

- [ ] **Step 5.3 — Import smoke test**

```
cd python && uv run python -c "from graph.nodes import scan_semantic_hotspots; print(scan_semantic_hotspots.__name__)"
```

Expected: `scan_semantic_hotspots`

- [ ] **Step 5.4 — Commit**

```
git add python/graph/nodes/__init__.py python/graph/runner.py
git commit -m "feat(graph): register semantic_hotspot_scan and its merge strategy"
```

---

## Task 6 — Extend `BusinessRiskGraphState`

**Files:**
- Modify: `python/graph/business_risk_state.py:1-20`

- [ ] **Step 6.1 — Add the new field**

The full file becomes:

```python
"""State contract for the stateless business risk pipeline."""

from __future__ import annotations

from typing import Any, TypedDict


class BusinessRiskGraphState(TypedDict, total=False):
    task_id: str
    run_id: str
    trace_id: str | None
    request: dict[str, Any]
    source_package: dict[str, Any]
    business_invariants: dict[str, Any]
    data_flow_paths: dict[str, Any]
    invariant_violations: dict[str, Any]
    method_issues: dict[str, Any]
    semantic_findings: dict[str, Any]
    business_risk_report: dict[str, Any]
    verified_risks: dict[str, Any]
```

Note: the shared `GraphState` in `python/graph/state.py` already has the business-risk keys declared; for consistency add `semantic_findings: Dict[str, Any]` to it too, right after `method_issues`.

- [ ] **Step 6.2 — Commit**

```
git add python/graph/business_risk_state.py python/graph/state.py
git commit -m "feat(state): declare semantic_findings on business risk graph state"
```

---

## Task 7 — `assess_business_risk` consumes semantic count

**Files:**
- Modify: `python/graph/nodes/business_risk.py:1-38`
- Test: `python/tests/graph/test_business_risk_assess.py`

- [ ] **Step 7.1 — Write failing tests for the assess upgrade**

Create `python/tests/graph/test_business_risk_assess.py`:

```python
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
```

- [ ] **Step 7.2 — Run tests to verify they fail**

```
cd python && uv run pytest tests/graph/test_business_risk_assess.py -v
```

Expected: FAIL — assertions on `level == "HIGH"` do not hold yet.

- [ ] **Step 7.3 — Update `assess_business_risk`**

Replace `python/graph/nodes/business_risk.py` with:

```python
"""Aggregate business risk findings from prepared source analysis."""

from __future__ import annotations

from graph.state import GraphState, NodeContext


def assess_business_risk(state: GraphState, ctx: NodeContext) -> GraphState:
    violations = state.get("invariant_violations", {})
    method_issues = state.get("method_issues", {})
    data_flow_paths = state.get("data_flow_paths", {})
    semantic_findings = state.get("semantic_findings", {})

    violation_count = len(violations.get("violations", [])) if isinstance(violations, dict) else 0
    issue_count = len(method_issues.get("issues", [])) if isinstance(method_issues, dict) else 0
    path_count = len(data_flow_paths.get("paths", [])) if isinstance(data_flow_paths, dict) else 0
    semantic_count = len(semantic_findings.get("items", [])) if isinstance(semantic_findings, dict) else 0

    if semantic_count > 0 or violation_count > 0:
        level = "HIGH"
    elif issue_count > 0 or path_count > 3:
        level = "MEDIUM"
    else:
        level = "LOW"

    if violation_count > 0:
        summary = "Potential business risk detected in state-changing flow"
    elif semantic_count > 0:
        summary = "Semantic analysis detected potential business risk in hotspots"
    elif issue_count > 0:
        summary = "Business risk hotspots require review"
    else:
        summary = "Business risk analysis completed"

    state["business_risk_report"] = {
        "level": level,
        "summary": summary,
        "violation_count": violation_count,
        "semantic_count": semantic_count,
        "method_issue_count": issue_count,
        "path_count": path_count,
        "need_human_review": level != "LOW",
        "status": "READY",
    }
    return state
```

- [ ] **Step 7.4 — Run tests to verify they pass**

```
cd python && uv run pytest tests/graph/test_business_risk_assess.py -v
```

Expected: 4 passed.

- [ ] **Step 7.5 — Make sure existing node tests still pass**

```
cd python && uv run pytest tests/graph/ -v
```

Expected: all green (existing `test_nodes.py` etc. do not exercise `assess_business_risk` behaviour that we changed).

- [ ] **Step 7.6 — Commit**

```
git add python/graph/nodes/business_risk.py tests/graph/test_business_risk_assess.py
git commit -m "feat(assess): promote level to HIGH on semantic findings, update summary"
```

---

## Task 8 — `business_risk_result.py` passes semantic data through

**Files:**
- Modify: `python/graph/business_risk_result.py:1-45`

- [ ] **Step 8.1 — Update result builder**

The full file becomes:

```python
"""Result assembly for the stateless business risk pipeline."""

from __future__ import annotations

from schemas.business_risk_review import BusinessRiskReviewRequest, BusinessRiskReviewResult
from graph.business_risk_state import BusinessRiskGraphState


def build_business_risk_result(
    request: BusinessRiskReviewRequest,
    state: BusinessRiskGraphState,
) -> BusinessRiskReviewResult:
    report = state.get("business_risk_report") or {}
    verified = state.get("verified_risks") or {}
    invariant_violations = state.get("invariant_violations") or {}
    method_issues = state.get("method_issues") or {}
    semantic_findings = state.get("semantic_findings") or {}

    level = str(report.get("level", "LOW")).lower()
    status = "completed"
    if report.get("need_human_review") or verified.get("need_human_review"):
        status = "human_review"

    executive_summary = report.get("summary") or "Business risk analysis completed"
    report_payload = {
        "overall_risk_level": level,
        "executive_summary": executive_summary,
        "invariant_violations": invariant_violations.get("violations", []),
        "method_issues": method_issues.get("issues", []),
        "semantic_findings": semantic_findings.get("items", []),
        "semantic_status": semantic_findings.get("status"),
        "items": verified.get("items", []),
    }

    proposed_memory_updates = {
        "business_risk_level": level,
        "violation_count": len(invariant_violations.get("violations", [])),
        "method_issue_count": len(method_issues.get("issues", [])),
        "semantic_count": len(semantic_findings.get("items", [])),
    }

    return BusinessRiskReviewResult(
        run_id=state.get("run_id", request.run_id),
        task_id=state.get("task_id", request.task_id),
        status=status,
        report=report_payload,
        proposed_memory_updates=proposed_memory_updates,
        trace_id=state.get("trace_id", request.trace_id),
    )
```

- [ ] **Step 8.2 — Commit**

```
git add python/graph/business_risk_result.py
git commit -m "feat(result): pass semantic_findings through to the business risk result"
```

---

## Task 9 — Wire node into `_build_business_risk_runner`

**Files:**
- Modify: `python/app/dependencies.py:11-27,191-199`

- [ ] **Step 9.1 — Import and register**

In `python/app/dependencies.py`:

Add `scan_semantic_hotspots` to the `from graph.nodes import (...)` block (alphabetical within the business-risk cluster):

```python
from graph.nodes import (
    analyze_diff,
    analyze_impact,
    analyze_performance,
    assess_business_risk,
    audit_security,
    check_invariants,
    classify_changes,
    deep_read_methods,
    extract_business_invariants,
    run_rag,
    run_rule_checks,
    scan_semantic_hotspots,
    score_risks,
    summarize,
    trace_data_flow,
    verify_business_risks,
)
```

Update the parallel group in `_build_business_risk_runner`:

```python
    builder.add_parallel_group([
        ("check_invariants", check_invariants),
        ("deep_read_methods", deep_read_methods),
        ("semantic_hotspot_scan", scan_semantic_hotspots),
    ])
```

- [ ] **Step 9.2 — Smoke test the runner wiring**

```
cd python && uv run python -c "
from app.dependencies import _build_business_risk_runner, _create_log_service, NoOpTelemetry
runner = _build_business_risk_runner(task_service=None, log_service=_create_log_service(telemetry=NoOpTelemetry()))
print('node count:', runner.count_nodes())
"
```

Expected: `node count: 6` (was 5, now 6 with the new node).

- [ ] **Step 9.3 — Commit**

```
git add python/app/dependencies.py
git commit -m "feat(wiring): register semantic_hotspot_scan in the business risk runner"
```

---

## Task 10 — End-to-end integration test

**Files:**
- Create: `python/tests/graph/test_business_risk_integration.py`

- [ ] **Step 10.1 — Write an integration test that exercises the full pipeline**

```python
"""End-to-end test for the business risk pipeline with semantic_hotspot_scan."""
from __future__ import annotations

from unittest.mock import Mock

from app.dependencies import _build_business_risk_runner, _create_log_service
from graph.business_risk_runner import BusinessRiskRunner
from schemas.business_risk_review import BusinessRiskReviewRequest, BusinessRiskSourcePackage, BusinessRiskSourceFile, BusinessRiskHotspot
from telemetry.hooks import NoOpTelemetry


def _mock_llm():
    llm = Mock()
    llm.chat_structured.return_value = {
        "has_risk": True,
        "category": "state_change",
        "severity": "high",
        "reason": "无事务边界",
        "evidence": "stock--",
        "suggestion": "@Transactional",
        "confidence": 0.9,
    }
    return llm


def test_full_pipeline_with_llm_finding():
    log_service = _create_log_service(telemetry=NoOpTelemetry())
    runner = _build_business_risk_runner(
        task_service=None, log_service=log_service, llm_client=_mock_llm(),
    )
    br_runner = BusinessRiskRunner(runner)

    request = BusinessRiskReviewRequest(
        run_id="run-1", task_id="task-1", project_id="p1", repo="r", branch="main",
        request_id="req-1",
        source_package=BusinessRiskSourcePackage(
            file_count=1,
            files=[BusinessRiskSourceFile(
                path="com/acme/Inventory.java",
                method_skeletons=[],
                hotspots=[BusinessRiskHotspot(
                    reason="库存扣减", snippet="stock--", start_line=10, end_line=15,
                )],
            )],
        ),
    )
    result = br_runner.run(request)

    assert result.status == "human_review"  # HIGH level triggers need_human_review
    assert result.report["overall_risk_level"] == "high"
    assert len(result.report["semantic_findings"]) == 1
    assert result.report["semantic_findings"][0]["source"] == "llm_semantic"
    assert result.report["semantic_status"] == "READY"
    assert result.proposed_memory_updates["semantic_count"] == 1


def test_full_pipeline_without_llm_still_completes():
    log_service = _create_log_service(telemetry=NoOpTelemetry())
    runner = _build_business_risk_runner(
        task_service=None, log_service=log_service, llm_client=None,
    )
    br_runner = BusinessRiskRunner(runner)

    request = BusinessRiskReviewRequest(
        run_id="run-2", task_id="task-2", project_id="p1", repo="r", branch="main",
        request_id="req-2",
        source_package=BusinessRiskSourcePackage(
            file_count=1,
            files=[BusinessRiskSourceFile(
                path="com/acme/Inventory.java",
                method_skeletons=[],
                hotspots=[BusinessRiskHotspot(
                    reason="库存扣减", snippet="stock--", start_line=10, end_line=15,
                )],
            )],
        ),
    )
    result = br_runner.run(request)

    assert result.status == "completed"
    assert result.report["semantic_findings"] == []
    assert result.report["semantic_status"] == "llm_skipped"
    assert result.proposed_memory_updates["semantic_count"] == 0
```

- [ ] **Step 10.2 — Run the integration test**

```
cd python && uv run pytest tests/graph/test_business_risk_integration.py -v
```

Expected: 2 passed.

- [ ] **Step 10.3 — Run the full Python test suite to confirm nothing regressed**

```
cd python && uv run pytest -q
```

Expected: all tests pass. (If any unrelated tests fail because of fixture drift, fix them in this step — they should be trivial.)

- [ ] **Step 10.4 — Commit**

```
git add python/tests/graph/test_business_risk_integration.py
git commit -m "test(integration): end-to-end business-risk pipeline with semantic_hotspot_scan"
```

---

## Task 11 — Lint + type-check

**Files:** (none)

- [ ] **Step 11.1 — Run ruff**

```
cd python && uv run ruff check .
```

Expected: no findings against the new files. If ruff flags anything, fix in place.

- [ ] **Step 11.2 — Run black --check**

```
cd python && uv run black --check .
```

Expected: clean. If not, `uv run black .` and commit the formatting.

- [ ] **Step 11.3 — Run mypy**

```
cd python && uv run mypy .
```

Expected: no new errors in the files we touched.

- [ ] **Step 11.4 — Final commit if any auto-formatting was applied**

```
git add -A
git commit -m "chore: apply ruff/black/mypy fixes to semantic hotspot work"
```

(Only if Steps 11.1-11.3 made changes.)

---

## Self-review checklist

- **Spec coverage:** every spec section (architecture, schema, state contract, node, assess, result, runner merge, dependencies, settings, tests, error handling) has a matching task — Tasks 1–11 cover them all.
- **Placeholder scan:** no TBD/TODO; all code blocks complete.
- **Type consistency:** `SemanticFindingSchema` is the same name everywhere; `scan_semantic_hotspots` function and `semantic_hotspot_scan` node name match across Tasks 3/5/9; `semantic_findings.items` / `status` / `scanned_count` / `reason` keys consistent in Tasks 3/4/6/7/8/10.
