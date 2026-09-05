"""LLM client - OpenAI-compatible API wrapper with structured output and retry."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from config.settings import AppSettings
from llm.metering import metered

logger = logging.getLogger(__name__)


class LLMStructuredOutputError(Exception):
    """Raised when LLM structured output fails after max retries."""

    def __init__(self, message: str, last_response: str | None = None) -> None:
        super().__init__(message)
        self.last_response = last_response


class LLMClient:
    """LLM client wrapping OpenAI-compatible API (DashScope/Qwen)."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        settings = settings or AppSettings()
        self._model = settings.llm_model
        self._client = OpenAI(
            base_url=settings.llm_api_base.rstrip("/"),
            api_key=settings.llm_api_key,
            timeout=60.0,
            max_retries=1,
        )

    @metered
    def _create_completion(self, **kwargs: Any) -> Any:
        """LLM 调用唯一落点：所有公共方法都经此发起请求。

        挂 @metered 切面，自动采集响应中的真实 token 用量（usage），
        业务方法无需感知计量逻辑。
        """
        return self._client.chat.completions.create(model=self._model, **kwargs)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        response = self._create_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat_structured(
        self,
        messages: list[dict[str, str]],
        output_schema: type[BaseModel],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        last_raw: str | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._create_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content or ""
                last_raw = raw
                parsed = json.loads(raw)
                validated = output_schema.model_validate(parsed)
                return validated.model_dump()
            except json.JSONDecodeError as e:
                logger.warning(
                    "LLM JSON parse failed attempt "
                    + str(attempt + 1)
                    + "/"
                    + str(max_retries + 1)
                    + ": "
                    + str(e)
                )
                if attempt < max_retries:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Output format error. Please output valid JSON matching the schema.",
                        }
                    )
                else:
                    raise LLMStructuredOutputError(
                        "JSON parse failed after " + str(max_retries + 1) + " attempts",
                        last_raw,
                    ) from e
            except Exception as e:
                if isinstance(e, LLMStructuredOutputError):
                    raise
                logger.warning(
                    "LLM structured output validation failed attempt "
                    + str(attempt + 1)
                    + "/"
                    + str(max_retries + 1)
                    + ": "
                    + str(e)
                )
                if attempt < max_retries:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Validation failed. Please fix and retry with correct schema.",
                        }
                    )
                else:
                    raise LLMStructuredOutputError(
                        "Structured output validation failed after "
                        + str(max_retries + 1)
                        + " attempts",
                        last_raw,
                    ) from e

        raise LLMStructuredOutputError("Unreachable", last_raw)
