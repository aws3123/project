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
    def _create_completion(self, model: str | None = None, **kwargs: Any) -> Any:
        """LLM 调用唯一落点：所有公共方法都经此发起请求。

        挂 @metered 切面，自动采集响应中的真实 token 用量（usage），
        业务方法无需感知计量逻辑。model 入参允许覆盖默认模型（如视觉 VL 模型），
        不传则使用配置模型。
        """
        return self._client.chat.completions.create(
            model=model or self._model,
            **kwargs,
        )

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

    # ------------------------------------------------------------------
    # 多模态视觉（VL）调用
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_image_as_data_url(image_path: str) -> str:
        """把本地 PNG 图片编码为 base64 data URL，供视觉模型作为 image_url 使用。"""
        import base64

        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    def _build_vision_content(
        self, prompt: str, image_paths: list[str]
    ) -> list[dict[str, Any]]:
        """构造 OpenAI 多模态 content（文本 + 多张图片）。

        视觉模型的 messages[].content 是一个数组，混合 text 与 image_url 项。
        """
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._encode_image_as_data_url(image_path)},
                }
            )
        return content

    def chat_vision(
        self,
        prompt: str,
        image_paths: list[str],
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> str:
        """对一张或多张图片执行多模态对话，返回纯文本响应。

        model 默认取配置中的 vlm_model（调用方需显式传入，避免误导）。
        """
        kwargs: dict[str, Any] = {
            "messages": [
                {"role": "user", "content": self._build_vision_content(prompt, image_paths)}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = self._create_completion(model=model, **kwargs)
        return response.choices[0].message.content or ""

    def chat_vision_structured(
        self,
        prompt: str,
        image_paths: list[str],
        output_schema: type[BaseModel],
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        max_retries: int = 2,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """多模态 + JSON 结构化输出。把首条消息的 content 换成混合文本+图片。"""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": self._build_vision_content(prompt, image_paths)}
        ]
        last_raw: str | None = None
        for attempt in range(max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                }
                if timeout is not None:
                    kwargs["timeout"] = timeout
                response = self._create_completion(model=model, **kwargs)
                raw = response.choices[0].message.content or ""
                last_raw = raw
                parsed = json.loads(raw)
                validated = output_schema.model_validate(parsed)
                return validated.model_dump()
            except json.JSONDecodeError as e:
                logger.warning(
                    "VL JSON parse failed attempt "
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
                        "VL JSON parse failed after "
                        + str(max_retries + 1)
                        + " attempts",
                        last_raw,
                    ) from e
            except Exception as e:
                if isinstance(e, LLMStructuredOutputError):
                    raise
                logger.warning(
                    "VL structured output validation failed attempt "
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
                        "VL structured output validation failed after "
                        + str(max_retries + 1)
                        + " attempts",
                        last_raw,
                    ) from e

        raise LLMStructuredOutputError("Unreachable", last_raw)
