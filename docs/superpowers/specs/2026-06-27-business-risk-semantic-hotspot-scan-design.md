# Business Risk: Semantic Hotspot Scan

- Date: 2026-06-27
- Status: approved
- Scope: Python AI layer — business risk pipeline only

## Problem

The business risk pipeline (`extract_business_invariants → trace_data_flow → [check_invariants ‖ deep_read_methods] → assess_business_risk → verify_business_risks`) is purely rule-based. It only recognises state-changing flows via keyword matches (`reserve`, `deduct`, `decrease`, `@Transactional` + Repository), so it misses semantically risky hotspots that don't trigger those patterns. Recall is low for non-trivial business semantics.

## Goal

Introduce a single LLM-powered node that reads the BFF-prepared AST hotspots and identifies business-state-change risks at the semantic level, while preserving the deterministic pipeline's testability, graceful degradation, and cost profile.

## Non-goals

- Do not replace existing rule nodes.
- Do not introduce an LLM call for every method skeleton (hotspots only).
- Do not build a feature-flag system, gray-release, or multi-model router.
- Do not modify the `verify_business_risks` node.

## Architecture

### New graph shape

```
extract_business_invariants → trace_data_flow →
  [check_invariants ‖ deep_read_methods ‖ semantic_hotspot_scan] →
assess_business_risk → verify_business_risks
```

`semantic_hotspot_scan` runs **in parallel** with `check_invariants` and `deep_read_methods` inside the existing `add_parallel_group`. All three depend only on upstream state (`source_package`, `business_invariants`, `data_flow_paths`) and are independent.

### New node: `python/graph/nodes/semantic_hotspot_scan.py`

- Inputs: `state["source_package"].files[*].hotspots[*]` + per-file context (`path`, `class_summary`, `annotations`, `method_skeletons[*].key_calls`).
- Guard: if `ctx.llm_client is None`, write `{items: [], status: "llm_skipped", scanned_count: N}` and return.
- For each hotspot, call `llm_client.chat_structured(messages, output_schema=SemanticFindingSchema)` with `temperature=0.1`, `max_tokens=512`.
- Concurrency bounded internally by `concurrent.futures.ThreadPoolExecutor(max_workers=settings.semantic_hotspot_concurrency)` (default 5). The node function itself is **synchronous** (matching `GraphRunner`'s sync signature); only the in-node LLM fan-out is concurrent.
- Per-call timeout: 15s (lower than `LLMClient`'s 60s default) so the node finishes within the runner's 45s parallel-phase window.
- Per-call failure is captured; does not abort the node.
- Filter: only items with `has_risk=true` enter `semantic_findings.items`. Items with `confidence < 0.6` have severity downgraded by one level.
- Status: `READY` if ≥1 call succeeded, `llm_failed` if all calls failed.

### System prompt

```
你是 Java 业务风险分析师。给定一个 hotspot 方法（BFF 层 AST 预筛出的"可疑代码片段"），
判断它是否包含隐含的业务状态变更风险。
关注：库存/余额/权益/数量等状态的非预期修改、缺少事务边界的状态变更、并发场景下的竞态、
状态机非法转换、跨聚合副作用。
输出 JSON，字段：has_risk(bool), category(str,可选), severity(high/medium/low),
reason(str,中文), evidence(str), suggestion(str,中文), confidence(0-1)。
若无业务风险，返回 has_risk=false。
```

### Output schema

```python
class SemanticFindingSchema(BaseModel):
    has_risk: bool
    category: str | None = None
    severity: Literal["high", "medium", "low"] = "low"
    reason: str = ""
    evidence: str = ""
    suggestion: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)
```

### State contract

`BusinessRiskGraphState` adds:

```python
semantic_findings: dict[str, Any]
# {
#   "items": [ {path, signature, category, severity, reason, evidence,
#              suggestion, confidence, source="llm_semantic"}, ... ],
#   "scanned_count": int,
#   "status": "READY" | "llm_skipped" | "llm_failed",
#   "reason": str | None,
# }
```

Shape intentionally mirrors `invariant_violations.violations` so downstream consumers can treat them uniformly.

## Changes to existing nodes

### `assess_business_risk`

```python
semantic_count = len(state.get("semantic_findings", {}).get("items", []))

if semantic_count > 0 or violation_count > 0:
    level = "HIGH"
elif issue_count > 0 or path_count > 3:
    level = "MEDIUM"
else:
    level = "LOW"

# summary branch addition:
if semantic_count > 0 and violation_count == 0:
    summary = "Semantic analysis detected potential business risk in hotspots"
```

### `graph/business_risk_result.py`

Add to `report_payload`:

```python
"semantic_findings": state.get("semantic_findings", {}).get("items", []),
"semantic_status": state.get("semantic_findings", {}).get("status"),
```

And to `proposed_memory_updates`:

```python
"semantic_count": len(state.get("semantic_findings", {}).get("items", [])),
```

### `verify_business_risks`

No change. It reads `invariant_violations` and `method_issues`; `semantic_findings` flows through the result builder separately.

### `app/dependencies.py`

Add `semantic_hotspot_scan` to the existing parallel group:

```python
builder.add_parallel_group([
    ("check_invariants", check_invariants),
    ("deep_read_methods", deep_read_methods),
    ("semantic_hotspot_scan", scan_semantic_hotspots),
])
```

### `graph/runner.py`

Add `semantic_findings` to `MERGE_STRATEGY`:

```python
MERGE_STRATEGY = {
    ...
    "semantic_findings": "replace",
}
```

## Configuration

Added to `config/settings.py` (`AppSettings`):

```python
semantic_hotspot_enabled: bool = True
semantic_hotspot_concurrency: int = 5
semantic_hotspot_confidence_threshold: float = 0.6
```

When `semantic_hotspot_enabled=False`, the node writes `{items: [], status: "disabled", scanned_count: 0}` and returns immediately.

## Error handling

- `ctx.llm_client is None` → `status: "llm_skipped"`, empty items.
- Per-hotspot LLM exception (timeout / JSON parse / schema validation) → captured, node continues with remaining hotspots.
- All hotspots fail → `status: "llm_failed"`, `reason` records last error.
- Any outcome: downstream `assess_business_risk` uses `.get()` and remains safe.

## Testing

| Test | Type | Coverage |
|---|---|---|
| `test_semantic_hotspot_scan_no_llm` | unit | `llm_client=None` → `llm_skipped`, downstream safe |
| `test_semantic_hotspot_scan_with_mock_llm` | unit | Mock LLM → items shape, severity, confidence |
| `test_semantic_hotspot_scan_llm_failure` | unit | Mock raises → `llm_failed`, items empty |
| `test_semantic_hotspot_scan_empty_hotspots` | unit | No hotspots → no LLM call, `READY` |
| `test_semantic_hotspot_scan_filters_no_risk` | unit | `has_risk=false` → not in items |
| `test_semantic_hotspot_scan_low_confidence_downgrades_severity` | unit | confidence<0.6 → severity downgraded |
| `test_assess_includes_semantic_count` | unit | assess promotes level to HIGH on semantic findings |
| `test_integration_business_risk_pipeline` | integration | full runner flow; result contains `semantic_findings` |

Reuse `tests/graph/` structure and `tests/conftest.py` fixtures.

## Files to add/modify

- **Add** `python/graph/nodes/semantic_hotspot_scan.py`
- **Add** `python/schemas/semantic_finding.py` (Pydantic schema)
- **Add** `tests/graph/test_semantic_hotspot_scan.py`
- **Modify** `python/graph/business_risk_state.py` (add `semantic_findings` field)
- **Modify** `python/graph/nodes/business_risk.py` (consume semantic count)
- **Modify** `python/graph/business_risk_result.py` (pass through)
- **Modify** `python/app/dependencies.py` (register node in parallel group)
- **Modify** `python/graph/runner.py` (add `semantic_findings` to `MERGE_STRATEGY`)
- **Modify** `python/config/settings.py` (add 3 settings)
- **Modify** `tests/graph/test_business_risk_assess.py` (extend for semantic count)

## Rollout / risk

- Additive change: existing rule pipeline still produces the same output when LLM is disabled or fails.
- Cost: hotspot count per request is typically < 10; at ~500 tokens per call (in+out), cost per request stays under a cent.
- Latency: parallel execution with rule nodes means LLM latency is hidden behind the slowest parallel branch, not additive.
- Rollback: set `SEMANTIC_HOTSPOT_ENABLED=false` to disable at runtime.
