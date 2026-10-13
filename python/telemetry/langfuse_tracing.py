"""Optional Langfuse v4 tracing with isolated failures and bounded IO capture."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import re
from contextlib import ExitStack, contextmanager
from functools import lru_cache
from threading import RLock
from typing import Any

from config.settings import AppSettings

logger = logging.getLogger(__name__)
_SENSITIVE = re.compile(
    r"api[_-]?key|secret|password|authorization|cookie|credential|"
    r"public[_-]?key|private[_-]?key|(?:^|[_-])token(?:$|[_-])",
    re.I,
)
_CREDENTIAL = re.compile(
    r"(?i)(bearer\s+\S+|(?:sk-|pk-)[a-z0-9_-]+|"
    r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+)"
)


def _shape(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            str(k): _shape(v, depth + 1)
            for k, v in list(value.items())[:30]
            if not _SENSITIVE.search(str(k))
        }
    if isinstance(value, (list, tuple)):
        return {"count": len(value)}
    if isinstance(value, str):
        return {"characters": len(value)}
    if value is None:
        return None
    return type(value).__name__


def _redact(value: Any, limit: int, depth: int = 0) -> Any:
    if depth > 6:
        return "[depth limit]"
    if isinstance(value, dict):
        return {
            str(k): (
                "[redacted]"
                if _SENSITIVE.search(str(k))
                else "[image omitted]"
                if str(k) in {"image_url", "image", "images"}
                else _redact(v, limit, depth + 1)
            )
            for k, v in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, limit, depth + 1) for v in value[:20]]
    if isinstance(value, str):
        if value.startswith("data:image/"):
            return "[image omitted]"
        return _CREDENTIAL.sub("[redacted]", value[:limit])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "model_dump"):
        return _redact(value.model_dump(mode="json"), limit, depth + 1)
    return type(value).__name__


class Observation:
    def __init__(
        self, raw, tracing: LangfuseTracing, metadata: dict | None = None
    ) -> None:
        self._raw, self._tracing = raw, tracing
        self._metadata = dict(metadata or {})

    def update(self, **fields: Any) -> None:
        if self._raw is None:
            return
        try:
            if "metadata" in fields:
                self._metadata.update(fields["metadata"])
                fields["metadata"] = dict(self._metadata)
            for field in ("input", "output"):
                if field in fields:
                    fields[field] = self._tracing.payload(fields[field])
            self._raw.update(**fields)
        except Exception as exc:
            logger.debug("Langfuse observation update skipped (%s)", type(exc).__name__)

    def error(self, exc: BaseException) -> None:
        # Never forward exception bodies: provider errors may contain prompts/keys.
        self.update(level="ERROR", status_message=type(exc).__name__)

    def completion(self, response: Any) -> None:
        """Use provider usage only; unknown/mock usage is left unset."""
        if self._raw is None:
            return
        try:
            fields: dict[str, Any] = {}
            model = getattr(response, "model", None)
            if model:
                fields["model"] = model
            choices = getattr(response, "choices", [])
            if choices:
                fields["output"] = getattr(choices[0].message, "content", None)
            usage = getattr(response, "usage", None)
            fields["metadata"] = {
                "usage_source": "provider" if usage is not None else "unavailable",
            }
            if usage is not None:
                details = {
                    key: value
                    for key, attr in (
                        ("input", "prompt_tokens"),
                        ("output", "completion_tokens"),
                        ("total", "total_tokens"),
                    )
                    if isinstance(value := getattr(usage, attr, None), int)
                    and value >= 0
                }
                if details:
                    fields["usage_details"] = details
            self.update(**fields)
        except Exception as exc:
            logger.debug("Langfuse generation usage skipped (%s)", type(exc).__name__)


class LangfuseTracing:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._client = None
        self._initialized = False
        self._lock = RLock()

    def start(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._initialized = True
            if not self.settings.langfuse_enabled:
                return
            if not (
                self.settings.langfuse_public_key and self.settings.langfuse_secret_key
            ):
                logger.warning(
                    "Langfuse enabled without project keys; tracing disabled"
                )
                return
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=self.settings.langfuse_public_key,
                    secret_key=self.settings.langfuse_secret_key,
                    base_url=self.settings.langfuse_base_url,
                    environment=self.settings.app_env,
                    release=self.settings.langfuse_release or None,
                    sample_rate=self.settings.langfuse_sample_rate,
                    timeout=self.settings.langfuse_timeout_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "Langfuse initialization skipped (%s)", type(exc).__name__
                )

    def payload(self, value: Any) -> Any:
        if not self.settings.langfuse_capture_content:
            return _shape(value)
        limit = self.settings.langfuse_max_content_chars
        sanitized = _redact(value, limit)
        encoded = json.dumps(sanitized, ensure_ascii=False)
        if len(encoded) > limit:
            return {"truncated": True, "preview": encoded[:limit]}
        return sanitized

    @contextmanager
    def observation(
        self,
        name: str,
        *,
        kind: str = "span",
        input: Any = None,
        metadata: dict | None = None,
        session_id: str | None = None,
        model: str | None = None,
        model_parameters: dict | None = None,
    ):
        self.start()
        stack = ExitStack()
        raw = None
        if self._client is not None:
            try:
                from langfuse import propagate_attributes

                attributes = {
                    key: str(value)[:200]
                    for key, value in (metadata or {}).items()
                    if isinstance(value, (str, bool, int, float))
                }
                stack.enter_context(
                    propagate_attributes(
                        session_id=session_id[:200] if session_id else None,
                        metadata=attributes,
                    )
                )
                options = {"name": name, "as_type": kind, "metadata": metadata or {}}
                if input is not None:
                    options["input"] = self.payload(input)
                if kind == "generation":
                    options.update(model=model, model_parameters=model_parameters)
                raw = stack.enter_context(
                    self._client.start_as_current_observation(**options)
                )
            except Exception as exc:
                logger.debug("Langfuse span start skipped (%s)", type(exc).__name__)
        observation = Observation(raw, self, metadata)
        try:
            yield observation
        except BaseException as exc:
            observation.error(exc)
            raise
        finally:
            # Do not pass application exceptions into the SDK; keep bodies local.
            try:
                stack.close()
            except Exception as exc:
                logger.debug("Langfuse span close skipped (%s)", type(exc).__name__)

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.to_thread(client.shutdown)
            except Exception as exc:
                logger.warning("Langfuse shutdown skipped (%s)", type(exc).__name__)


@lru_cache
def get_langfuse_tracing() -> LangfuseTracing:
    return LangfuseTracing(AppSettings())


def traced_operation(name: str, *, kind: str = "span"):
    """Wrap async graph operations without capturing dependency objects."""

    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            bound = signature.bind_partial(*args, **kwargs).arguments
            state = bound.get("state") or {}
            metadata = {
                key: str(state[key])
                for key in ("task_id", "run_id", "graph_version")
                if isinstance(state, dict) and state.get(key) is not None
            }
            with get_langfuse_tracing().observation(
                name,
                kind=kind,
                input=state or None,
                metadata=metadata,
            ) as observation:
                result = await fn(*args, **kwargs)
                observation.update(output=result)
                statuses = (
                    result.get("node_status") if isinstance(result, dict) else None
                )
                if isinstance(statuses, dict) and statuses:
                    observation.update(metadata={**metadata, "node_status": statuses})
                    if any(s in {"FAILED", "CIRCUIT_OPEN"} for s in statuses.values()):
                        observation.update(level="WARNING", status_message="degraded")
                return result

        return wrapped

    return decorate
