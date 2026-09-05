"""ReAct 循环代理 —— 让 LLM 在关键节点上可自主"思考→调工具→观察→再思考"。

ReAct = **Rea**soning + **Act**ing：
- 固定管道里，每个 LLM 节点只做"一次调用、一次回答"（term → answer）。
- ReAct 模式下，同一个节点 fork 出一个循环：LLM 每一步决定是
  「调用某个工具取证」还是「给出最终答案」，直到步数上限或收敛。

为什么需要？
  代码审查里很多证据（调用链、历史事故、AST 结构）并不是一次性全给 LLM
  就能看准的。开启 ReAct 后，模型可以主动去 registry 里按需取证据，
  再下结论——适合复杂 / 高风险的审查。

护栏：
  - max_steps 步数上限，防止无限循环（多次 LLM 调用，代价高）
  - 超步数 / 循环内 LLM 失败 → 自动回退到单次结构化调用，保证有输出
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from llm.client import LLMStructuredOutputError
from tools.base import ToolContext

logger = logging.getLogger(__name__)

# ReAct 单节点循环步数上限（每步 = 1 次 LLM 决策 + 可能的 1 次工具调用）
DEFAULT_MAX_STEPS = 5


# 每步决策的结构化 schema：要么调工具，要么给最终答案
class _ReactDecision(BaseModel):
    action: Literal["call_tool", "final_answer"]
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    # 最终答案：要求是 JSON 字符串（安全/性能节点 → {"findings": [...]}，
    # 语义节点 → 对应 schema）
    final_text: str | None = None


class ReActAgent:
    """对单个 LLM 节点执行 ReAct 循环。"""

    def __init__(
        self,
        llm_client: Any,
        registry: Any,
        task_id: str,
        allowed_tools: list[str] | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        node_name: str = "react",
    ) -> None:
        self._llm = llm_client
        self._registry = registry
        self._task_id = task_id
        self._allowed: set[str] = set(allowed_tools or [])
        self._max_steps = max_steps
        self._node = node_name

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def run(
        self,
        system_prompt: str,
        user_content: str,
        output_schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> tuple[Any, list[dict]]:
        """执行 ReAct 循环。

        Returns:
            (result, trace)
            - result: 收敛结果。若传了 output_schema → 已校验并 model_dump 的 dict；
              否则为 JSON 解析后的 dict（若非 JSON 则为原始 str）。
            - trace: 工具调用轨迹（供 tool_logs 落盘）。
        """
        base_messages = [
            {"role": "system", "content": self._build_system(system_prompt)},
            {"role": "user", "content": user_content},
        ]
        messages: list[dict[str, str]] = list(base_messages)
        trace: list[dict] = []

        result: Any | None = None
        for _step in range(1, self._max_steps + 1):
            decision = self._ask_decision(messages, temperature, max_tokens)
            if decision is None:
                break  # 决策调用失败 → 走回退

            action = decision.get("action")
            if action == "call_tool":
                tool_name = decision.get("tool_name")
                if tool_name not in self._allowed:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"工具 '{tool_name}' 不可用，可用：{sorted(self._allowed)}。"
                                "请调用可用工具，或直接输出最终答案。"
                            ),
                        }
                    )
                    continue
                observation = self._call_tool(
                    tool_name, decision.get("arguments") or {}
                )
                trace.append(
                    {
                        "node": self._node,
                        "tool": tool_name,
                        "arguments": decision.get("arguments") or {},
                        "method": "react_tool",
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"工具 {tool_name} 的观察结果：\n"
                            f"{_truncate(observation, 4000)}"
                        ),
                    }
                )
                continue

            final_text = decision.get("final_text")
            if final_text:
                result = self._coerce(final_text, output_schema)
                break
            messages.append(
                {"role": "user", "content": "请给出最终答案(final_text)。"}
            )

        # 步数超限 / 循环内失败 → 回退为单次调用，保证有输出
        if result is None:
            result = self._fallback(base_messages, output_schema, temperature, max_tokens)

        return result, trace

    # ------------------------------------------------------------------
    # 内部：循环的每一步
    # ------------------------------------------------------------------

    def _ask_decision(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> dict | None:
        """让 LLM 决定当前步是调工具还是给终答。失败返回 None（触发回退）。"""
        try:
            raw = self._llm.chat_structured(
                messages=messages,
                output_schema=_ReactDecision,
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries=1,
            )
        except (LLMStructuredOutputError, Exception):
            logger.warning(
                "ReAct decision failed for node=%s task=%s, falling back",
                self._node,
                self._task_id,
                exc_info=True,
            )
            return None
        return raw

    def _call_tool(self, tool_name: str, arguments: dict) -> str:
        """调用 registry 里的工具，返回可读的观察字符串（异常降级为错误信息）。"""
        try:
            result = self._registry.run(
                tool_name,
                arguments,
                ToolContext(task_id=self._task_id),
            )
            payload = result.payload
            return (
                json.dumps(payload, ensure_ascii=False, default=str)[:4000]
                if not _is_scalar(payload)
                else str(payload)
            )
        except Exception as exc:
            logger.warning(
                "ReAct tool %s failed for task=%s: %s",
                tool_name,
                self._task_id,
                exc,
            )
            return f"工具 {tool_name} 执行失败：{exc}"

    def _coerce(
        self, final_text: str, output_schema: type[BaseModel] | None
    ) -> Any:
        """把模型的 final_text 收敛为可用结果：优先按 output_schema 校验，否则 JSON 解析。"""
        try:
            parsed = json.loads(final_text)
        except json.JSONDecodeError:
            # 终答不是 JSON：若有 schema 则走回退保证结构，否则返回原文
            if output_schema is not None:
                return None
            return final_text
        if output_schema is not None:
            try:
                return output_schema.model_validate(parsed).model_dump()
            except Exception:
                logger.warning(
                    "ReAct final answer failed schema validation for node=%s",
                    self._node,
                    exc_info=True,
                )
                return None
        return parsed

    def _fallback(
        self,
        base_messages: list[dict[str, str]],
        output_schema: type[BaseModel] | None,
        temperature: float,
        max_tokens: int,
    ) -> Any:
        """回退为单次调用（等价于非 ReAct 的原路径），保证节点有输出。"""
        try:
            if output_schema is not None:
                return self._llm.chat_structured(
                    messages=base_messages,
                    output_schema=output_schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            raw = self._llm.chat(
                messages=base_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._coerce(raw, None)
        except Exception:
            logger.warning(
                "ReAct fallback failed for node=%s task=%s",
                self._node,
                self._task_id,
                exc_info=True,
            )
            return None

    def _build_system(self, system_prompt: str) -> str:
        """把 nodes 自带的系统提示 + 可用工具清单拼成最终的 system prompt。"""
        tool_manifest = self._registry.describe()
        available = [t for t in tool_manifest if t["name"] in self._allowed]
        tool_desc = "\n".join(
            f"- {t['name']}: {t.get('description') or '(无描述)'}"
            for t in available
        ) or "(无可用工具)"
        return (
            f"{system_prompt}\n\n"
            "你可以按需调用下面的工具来获取额外证据（工具调用结果会作为观察反馈给你），"
            "直到证据足够再输出最终答案。\n"
            "每次响应必须是合法 JSON，格式：\n"
            '  {"action":"call_tool","tool_name":"<工具名>","arguments":{...}}\n'
            "或\n"
            '  {"action":"final_answer","final_text":"<最终答案的JSON字符串>"}\n\n'
            f"可用工具：\n{tool_desc}"
        )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None