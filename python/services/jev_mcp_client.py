"""Client for the optional Jev review-routing MCP server."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config.settings import AppSettings


class JevMCPClient:
    """Calls the shared Jev review-routing MCP tool over Streamable HTTP."""

    def __init__(self, settings: AppSettings) -> None:
        self._url = settings.jev_mcp_url
        self._timeout_seconds = settings.jev_mcp_timeout_seconds

    async def classify(self, change_context: dict[str, Any]) -> dict[str, Any]:
        async with asyncio.timeout(self._timeout_seconds):
            async with streamable_http_client(self._url) as (
                read_stream,
                write_stream,
                _get_session_id,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "classify_review_route",
                        {"change_context": change_context},
                    )

        if result.isError:
            raise RuntimeError("Jev routing MCP returned an error")

        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured

        # FastMCP versions may serialize a dictionary as a JSON text block.
        for item in result.content:
            text = getattr(item, "text", None)
            if not text:
                continue
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded

        raise RuntimeError("Jev routing MCP returned an invalid response")
