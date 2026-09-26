"""Optional Jev MCP routing node for additional review agents."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from config.settings import AppSettings
from graph.state import GraphState, NodeContext
from services.jev_mcp_client import JevMCPClient

logger = logging.getLogger(__name__)
MAX_ROUTING_DIFF_CHARS = 12_000
MAX_ROUTING_FILES = 12


@lru_cache(maxsize=1)
def _client() -> JevMCPClient:
    return JevMCPClient(AppSettings())


def _build_context(state: GraphState) -> dict[str, Any]:
    request = state.get("request", {}) or {}
    analysis = state.get("diff_analysis", {}) or {}
    summary = analysis.get("summary", {}) or {}
    files: list[dict[str, str]] = []
    remaining = MAX_ROUTING_DIFF_CHARS

    for file in (request.get("files", []) or [])[:MAX_ROUTING_FILES]:
        if remaining <= 0:
            break
        diff = str(file.get("diff", ""))
        excerpt = diff[: min(2_000, remaining)]
        remaining -= len(excerpt)
        files.append({"path": str(file.get("path", "")), "diff_excerpt": excerpt})

    entities = analysis.get("entities", []) or []
    compact_entities = [
        {
            "name": str(entity.get("name", "")),
            "annotations": [
                str(annotation)
                for annotation in (entity.get("annotations", []) or [])[:8]
                if isinstance(annotation, str)
            ],
        }
        for entity in entities[:32]
        if isinstance(entity, dict)
    ]

    metadata = request.get("metadata", {}) or {}
    review_focus = ""
    if isinstance(metadata, dict):
        review_focus = str(
            metadata.get("reviewFocus") or metadata.get("question") or ""
        )[:500]

    return {
        "review_focus": review_focus,
        "files": files,
        "diff_summary": {
            "added_lines": summary.get("added_lines", 0),
            "deleted_lines": summary.get("deleted_lines", 0),
            "languages": summary.get("languages", []),
            "risk_flags": summary.get("riskFlags", []),
        },
        "layers": (state.get("classification", {}) or {}).get("layers", []),
        "changed_entities": compact_entities,
        "impact": {
            "affected_file_count": len(
                (state.get("impact_radius", {}) or {}).get("affected_files", [])
            ),
            "total_impact_score": (state.get("impact_radius", {}) or {}).get(
                "total_impact_score", 0
            ),
        },
        "risk_preferences": request.get("riskPreferences", {}),
    }


async def classify_review_route(
    state: GraphState, ctx: NodeContext
) -> GraphState:
    """Ask Jev for an optional reviewer suggestion; fail open to legacy rules."""
    try:
        route_result = await _client().classify(_build_context(state))
        confidence = float(route_result.get("confidence", -1))
        settings = AppSettings()
        accepted = (
            route_result.get("route")
            in {"security", "performance", "both", "rules_only"}
            and settings.jev_route_confidence_threshold <= confidence <= 1.0
        )
        state["jev_route"] = {
            "route": route_result.get("route"),
            "confidence": confidence,
            "accepted": accepted,
            "model": route_result.get("model"),
        }
        if accepted:
            logger.info(
                "Jev review route accepted taskId=%s route=%s confidence=%.3f",
                ctx.task_id,
                route_result["route"],
                confidence,
            )
        else:
            logger.info(
                "Jev review route below threshold taskId=%s confidence=%.3f",
                ctx.task_id,
                confidence,
            )
    except Exception as exc:
        # Routing is advisory. MCP/API outages must never fail a code review.
        logger.warning(
            "Jev review routing unavailable taskId=%s error=%s",
            ctx.task_id,
            type(exc).__name__,
        )
    return state
