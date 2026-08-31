from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from config.settings import AppSettings

logger = logging.getLogger(__name__)


class BffUnavailableError(Exception):
    """Raised when BFF service is unavailable or unhealthy."""


@dataclass
class AstChunk:
    """A single AST-parsed code chunk from BFF."""

    content: str
    language: str
    file_path: str
    start_line: int
    end_line: int
    chunk_type: str       # class / method / block / fallback
    name: str              # entity name (e.g., "UserService" or "findByUsername")
    fully_qualified_name: str
    signature: str         # e.g., "public User findByUsername(String username)"
    parent_class: str | None  # Parent class name if this is a method chunk
    ast_status: str        # parsed / fallback / boundary_unclear


class BffAstClient:
    """Client for calling BFF AST parsing endpoint."""

    def __init__(self, settings: AppSettings | None = None):
        self.settings = settings or AppSettings()
        self.base_url = self.settings.bff_base_url.rstrip("/")
        self.timeout = self.settings.bff_chunk_timeout
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.bff_api_key:
            self.headers["X-API-Key"] = self.settings.bff_api_key

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Ping BFF actuator/health endpoint.

        Returns True if healthy.
        Raises BffUnavailableError if BFF is unreachable or unhealthy.
        """
        url = f"{self.base_url}/actuator/health"
        try:
            resp = httpx.get(url, timeout=10, headers=self.headers)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "UNKNOWN")
                if status == "UP":
                    logger.info("BFF health check passed: %s", status)
                    return True
                logger.warning("BFF health check: status=%s", status)
                raise BffUnavailableError(f"BFF status is {status}")
            raise BffUnavailableError(f"BFF health check returned HTTP {resp.status_code}")
        except httpx.ConnectError as e:
            raise BffUnavailableError(f"Cannot connect to BFF at {self.base_url}: {e}") from e
        except httpx.TimeoutException as e:
            raise BffUnavailableError(f"BFF health check timed out: {e}") from e

    # ------------------------------------------------------------------
    # AST parse
    # ------------------------------------------------------------------

    def parse_code(
        self,
        code_text: str,
        language: str,
        file_path: str = "inline",
    ) -> list[AstChunk]:
        """Send code to BFF for AST-based parsing.

        Args:
            code_text: Source code text
            language: Programming language (java/python/typescript/sql)
            file_path: Optional file path for BFF context

        Returns:
            List of AstChunk objects with metadata.

        Raises:
            BffUnavailableError: If BFF is unreachable.
        """
        url = f"{self.base_url}/api/internal/chunk"
        payload = {
            "sourceCode": code_text,
            "language": language,
            "filePath": file_path,
            "maxChars": self.settings.bff_chunk_max_chars,
            "overlap": self.settings.bff_chunk_overlap,
        }

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
        except httpx.ConnectError as e:
            logger.error("BFF connection failed: %s", e)
            raise BffUnavailableError(f"Cannot connect to BFF: {e}") from e
        except httpx.TimeoutException as e:
            logger.error("BFF request timed out after %ds: %s", self.timeout, e)
            raise BffUnavailableError(f"BFF request timed out: {e}") from e

        if resp.status_code != 200:
            logger.error("BFF returned HTTP %d: %s", resp.status_code, resp.text[:200])
            raise BffUnavailableError(f"BFF returned HTTP {resp.status_code}")

        data: dict[str, Any] = resp.json()
        raw_chunks = data.get("chunks", [])

        if not raw_chunks:
            logger.warning("BFF returned 0 chunks for code (%d chars)", len(code_text))
            # Return single fallback chunk
            return [self._make_fallback_chunk(code_text, language, file_path)]

        return [self._parse_chunk(chunk, language, file_path) for chunk in raw_chunks]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_chunk(raw: dict, default_lang: str, default_path: str) -> AstChunk:
        """Parse a raw BFF chunk dict into AstChunk."""
        metadata = raw.get("metadata", {}) or {}
        return AstChunk(
            content=raw.get("content", ""),
            language=metadata.get("language", default_lang),
            file_path=raw.get("filePath", default_path),
            start_line=raw.get("startLine", 0),
            end_line=raw.get("endLine", 0),
            chunk_type=raw.get("chunkType", "block"),
            name=raw.get("name", ""),
            fully_qualified_name=raw.get("fullyQualifiedName", ""),
            signature=metadata.get("signature", ""),
            parent_class=metadata.get("parentClass"),
            ast_status="parsed",
        )

    @staticmethod
    def _make_fallback_chunk(code_text: str, language: str, file_path: str) -> AstChunk:
        """Create a fallback chunk when BFF returns no chunks."""
        return AstChunk(
            content=code_text,
            language=language,
            file_path=file_path,
            start_line=1,
            end_line=code_text.count("\n") + 1,
            chunk_type="fallback",
            name="",
            fully_qualified_name="",
            signature="",
            parent_class=None,
            ast_status="fallback",
        )

    def parse_code_with_fallback(
        self,
        code_text: str,
        language: str,
        file_path: str = "inline",
    ) -> list[AstChunk]:
        """Like parse_code, but returns fallback chunks on BFF error instead of raising."""
        try:
            return self.parse_code(code_text, language, file_path)
        except BffUnavailableError as e:
            logger.warning("BFF unavailable, using fallback chunk: %s", e)
            return [self._make_fallback_chunk(code_text, language, file_path)]
