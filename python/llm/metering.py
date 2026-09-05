"""Token 用量计量（AOP 装饰器 + 任务级 ContextVar 累加器）。

作用：
    - metered 装饰器：横切拦截 LLM 调用边界，自动采集响应中的真实 usage，
      与业务逻辑（审查节点）完全解耦，任何节点调 LLM 都被自动计量。
    - ContextVar 累加器：按"任务"隔离用量（每个任务独立 TokenUsage 实例）。
    - 线程语义：asyncio.to_thread 会复制当前 context 到工作线程，
      ContextVar 持有的是共享可变对象引用，线程内累加主线程可见，
      天然支持异步任务的跨线程聚合。
"""

from __future__ import annotations

import contextvars
import functools
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class TokenUsage:
    """可变累加器（作为 ContextVar 的共享值，支持跨线程累加）。"""

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def add(
        self,
        prompt: int,
        completion: int,
        total: int,
        model: str | None = None,
    ) -> None:
        self.prompt_tokens += prompt or 0
        self.completion_tokens += completion or 0
        self.total_tokens += total or 0
        if model and not self.model:
            self.model = model

    def snapshot(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
        }


_current: contextvars.ContextVar[TokenUsage | None] = contextvars.ContextVar(
    "review_token_usage", default=None
)


def record_usage(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    model: str | None = None,
) -> None:
    """把一次 LLM 调用的真实用量累加到当前任务的计量器。

    无计量上下文（非任务链路，如独立脚本）时静默忽略，保证零侵入。
    """
    usage = _current.get()
    if usage is not None:
        usage.add(
            prompt_tokens or 0,
            completion_tokens or 0,
            total_tokens or 0,
            model,
        )


class MeteringScope:
    """任务级计量作用域：进入时重置累加器，退出时自动清理。

    用法（review_consumer 处理单个任务时）::

        with MeteringScope():
            result = await asyncio.to_thread(process_message, request)
            usage = MeteringScope.current().snapshot()
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model
        self._token: contextvars.Token[TokenUsage | None] | None = None

    def __enter__(self) -> "MeteringScope":
        self._token = _current.set(TokenUsage(self._model))
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._token is not None:
            _current.reset(self._token)
            self._token = None

    @property
    def usage(self) -> TokenUsage | None:
        return _current.get()

    @staticmethod
    def current() -> TokenUsage | None:
        return _current.get()


def metered(fn: F) -> F:
    """AOP 切面：包装 LLM 底层调用，从响应 usage 采集真实 token 用量。

    适用对象：返回 OpenAI-compatible completion 响应的内部方法
    （见 LLMClient._create_completion）。业务方法无需任何改动即被计量。
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = fn(*args, **kwargs)
        usage = getattr(result, "usage", None)
        if usage is not None:
            record_usage(
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                getattr(usage, "total_tokens", None),
                getattr(result, "model", None),
            )
        return result

    return wrapper  # type: ignore[return-value]
