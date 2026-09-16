"""LLM client - OpenAI-compatible API wrapper with structured output and retry."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel

from config.settings import AppSettings
from llm.metering import metered

logger = logging.getLogger(__name__)


class LLMStructuredOutputError(Exception):
    """Raised when LLM structured output fails after max retries."""

    def __init__(self, message: str, last_response: str | None = None) -> None:
        super().__init__(message)
        self.last_response = last_response


class _MockMessage:
    """纯 mock 响应的最小 message 结构（兼容 choices[0].message.content 访问）。"""

    __slots__ = ("content", "reasoning_content")

    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning_content = None


class _MockChoice:
    __slots__ = ("message", "finish_reason")

    def __init__(self, content: str) -> None:
        self.message = _MockMessage(content)
        self.finish_reason = "stop"


class _MockCompletion:
    """纯 mock 响应的最小 completion 结构，供上层零改动复用。"""

    __slots__ = ("choices", "usage", "model")

    def __init__(self, content: str) -> None:
        self.choices = [_MockChoice(content)]
        self.usage = None
        self.model = None


def _mock_field_value(annotation: Any) -> Any:
    """按字段类型生成满足 schema 校验的 mock 默认值（支持嵌套模型）。"""
    import enum
    import types
    import typing

    from pydantic import BaseModel

    origin = typing.get_origin(annotation)
    if origin is typing.Union or (hasattr(types, "UnionType") and origin is types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return None if not args else _mock_field_value(args[0])
    if origin in (list, dict) or annotation in (list, dict, typing.List, typing.Dict):
        return []
    if origin is typing.Literal:
        return typing.get_args(annotation)[0]
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return list(annotation)[0].value
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _mock_model(annotation)
    return None


def _mock_model(schema: type[BaseModel]) -> dict[str, Any]:
    """为结构化输出 schema 生成一份能通过 Pydantic 校验的 mock 数据。"""
    return {
        name: _mock_field_value(field.annotation)
        for name, field in schema.model_fields.items()
    }


def _extract_json(raw: str) -> str:
    """从 LLM 原始输出中提取 JSON 文本。

    llama.cpp 部署的 Qwen3 经常把 JSON 包在 ```json ``` Markdown 代码围栏里，
    直接 json.loads 会因反引号而失败。先剥掉围栏，再截取首个 { 到末个 }。
    已是纯 JSON 时原样返回。
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text


class LLMClient:
    """LLM client wrapping OpenAI-compatible API (DashScope/Qwen)."""

    # 类级共享信号量：全局 LLM 调用并发限额（独立于消费拉取并发）
    _concurrency_semaphore: asyncio.Semaphore | None = None

    def __init__(self, settings: AppSettings | None = None) -> None:
        settings = settings or AppSettings()
        self._model = settings.llm_model
        self._disable_thinking = settings.llm_disable_thinking
        self._mock_delay_seconds = settings.llm_mock_delay_seconds
        if LLMClient._concurrency_semaphore is None:
            LLMClient._concurrency_semaphore = asyncio.Semaphore(
                settings.llm_max_concurrency
            )
        self._client = AsyncOpenAI(
            base_url=settings.llm_api_base.rstrip("/"),
            api_key=settings.llm_api_key,
            timeout=60.0,
            max_retries=1,
        )

    @metered
    async def _create_completion(
        self,
        model: str | None = None,
        output_schema: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> Any:
        """LLM 调用唯一落点：所有公共方法都经此发起请求。

        挂 @metered 切面，自动采集响应中的真实 token 用量（usage），
        业务方法无需感知计量逻辑。model 入参允许覆盖默认模型（如视觉 VL 模型），
        不传则使用配置模型。llm_disable_thinking 开启时，通过 llama.cpp 的
        chat_template_kwargs 关闭 Qwen3 的思考模式，避免白烧 thinking token。
        output_schema 仅压测纯 mock 模式使用：mock 开启时按 schema 生成
        能通过 Pydantic 校验的假响应，不发起真实 LLM 请求。
        """
        if self._disable_thinking:
            extra_body = kwargs.setdefault("extra_body", {})
            extra_body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        sem = LLMClient._concurrency_semaphore
        if sem is not None:
            async with sem:
                return await self._call(model, kwargs, output_schema)
        return await self._call(model, kwargs, output_schema)

    async def _call(
        self,
        model: str | None,
        kwargs: dict[str, Any],
        output_schema: type[BaseModel] | None = None,
    ) -> Any:
        if self._mock_delay_seconds > 0:
            # 压测开关：固定延迟模拟 LLM 推理耗时，异步 sleep 不阻塞事件循环。
            # 纯 mock 模式：延迟后直接返回模拟响应，不再真实调用上游 LLM，
            # 避免压测把 llama.cpp 压爆导致排空失败。
            await asyncio.sleep(self._mock_delay_seconds)
            if output_schema is not None:
                content = json.dumps(_mock_model(output_schema), ensure_ascii=False)
            else:
                content = '{"findings":[]}'
            return _MockCompletion(content)
        return await self._client.chat.completions.create(
            model=model or self._model,
            **kwargs,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        response = await self._create_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def chat_structured(
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
                response = await self._create_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    output_schema=output_schema,
                )
                raw = _extract_json(response.choices[0].message.content or "")
                last_raw = raw
                parsed = json.loads(raw)
                validated = output_schema.model_validate(parsed)
                return validated.model_dump()
            except json.JSONDecodeError as e:
                finish_reason = getattr(response.choices[0], "finish_reason", None)
                reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                logger.warning(
                    "LLM JSON parse failed attempt "
                    + str(attempt + 1)
                    + "/"
                    + str(max_retries + 1)
                    + ": "
                    + str(e)
                    + " finish="
                    + str(finish_reason)
                    + " raw_head="
                    + repr(raw[:200])
                    + " reasoning_head="
                    + repr((reasoning or "")[:200])
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

    async def chat_vision(
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
        response = await self._create_completion(model=model, **kwargs)
        return response.choices[0].message.content or ""

    async def chat_vision_structured(
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
                    "output_schema": output_schema,
                }
                if timeout is not None:
                    kwargs["timeout"] = timeout
                response = await self._create_completion(model=model, **kwargs)
                raw = _extract_json(response.choices[0].message.content or "")
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
