"""MCP tool that asks Jev to choose an optional review scope."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from config.settings import AppSettings

logger = logging.getLogger(__name__)
settings = AppSettings()

mcp = FastMCP(
    "sentinel-jev-review-router",
    instructions=(
        "Choose an additional code-review scope from the provided fixed options. "
        "This tool only recommends routing; the calling application executes it."
    ),
    host=settings.jev_mcp_host,
    port=settings.jev_mcp_port,
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "jev-mcp:8001",
            "localhost:8001",
            "127.0.0.1:8001",
        ],
    ),
)

ALLOWED_ROUTES = {"security", "performance", "both", "rules_only"}


@mcp.tool()
async def classify_review_route(change_context: dict[str, Any]) -> dict[str, Any]:
    """Select additional security/performance reviewers for a code change.

    The surrounding application keeps its existing deterministic reviewers and
    only uses this choice to add reviewers when Jev returns enough confidence.
    """
    if not settings.typesafe_api_key.strip():
        raise RuntimeError("TypeSafe API key is not configured")

    payload = {
        "model": settings.jev_model,
        "state": change_context,
        "questions": {
            "review_route": {
                "type": "choice",
                "instructions": (
                    "Which additional code review scope is most useful for this "
                    "change? Respect the requested review focus when present. "
                    "Choose rules_only if neither semantic reviewer adds value."
                ),
                "criteria": {
                    "security": "Add the security reviewer only.",
                    "performance": "Add the performance reviewer only.",
                    "both": "Add both security and performance reviewers.",
                    "rules_only": "Do not add a semantic reviewer; keep rule checks.",
                },
            }
        },
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.jev_api_timeout_seconds
        ) as client:
            response = await client.post(
                settings.typesafe_api_url,
                headers={
                    "Authorization": f"Bearer {settings.typesafe_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Jev API returned HTTP %s", exc.response.status_code)
        raise RuntimeError("Jev API request failed") from None
    except (httpx.RequestError, ValueError) as exc:
        logger.warning("Jev API request failed: %s", type(exc).__name__)
        raise RuntimeError("Jev API request failed") from None

    try:
        answer = body["answers"]["review_route"]
        route = str(answer["choice"])
        confidence = float(answer["confidence"])
        probabilities = answer.get("probabilities", {})
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Jev API returned an invalid route result") from None

    if route not in ALLOWED_ROUTES or not 0.0 <= confidence <= 1.0:
        raise RuntimeError("Jev API returned an invalid route result")

    return {
        "route": route,
        "confidence": confidence,
        "probabilities": probabilities,
        "model": body.get("model", settings.jev_model),
        "usage": body.get("usage", {}),
    }


def main() -> None:
    """Run the internal Streamable HTTP MCP server."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
