"""ReActAgent 单元测试 —— 用假 LLM / 假 注册表 验证循环与回退。"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from services.react_agent import ReActAgent


class _Finding(BaseModel):
    title: str = Field(description="发现标题")
    severity: str = "LOW"


# ---------------------------------------------------------------------------
# 假依赖
# ---------------------------------------------------------------------------


class _FakeLLM:
    """chat_structured 按脚本依次返回决策；chat 用于回退。"""

    def __init__(self, decisions: list[dict], fallback_text: str = "") -> None:
        self._decisions = list(decisions)
        self.fallback_text = fallback_text
        self.decision_calls = 0

    def chat_structured(self, messages, output_schema, **kwargs) -> dict:
        self.decision_calls += 1
        if self._decisions:
            return self._decisions.pop(0)
        # 脚本耗尽 → 若有 output_schema 则返回合法性校验后的终止决策
        raise RuntimeError("decisions exhausted")

    def chat(self, messages, **kwargs) -> str:
        return self.fallback_text


class _FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def describe(self) -> list[dict]:
        return [
            {"name": "code_knowledge_graph", "description": "查询调用链", "parameters": None}
        ]

    def run(self, name, payload, context) -> object:
        self.calls.append((name, payload))
        return type("R", (), {"payload": {"affected": ["UserService.java"]}})()


def _agent(llm, registry=None):
    return ReActAgent(
        llm,
        registry or _FakeRegistry(),
        task_id="task-1",
        allowed_tools=["code_knowledge_graph"],
        node_name="security",
    )


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_react_loop_calls_tool_then_final_answer():
    llm = _FakeLLM(
        [
            {
                "action": "call_tool",
                "tool_name": "code_knowledge_graph",
                "arguments": {"changed_files": ["A.java"]},
            },
            {
                "action": "final_answer",
                "final_text": json.dumps({"title": "SQL注入风险", "severity": "HIGH"}),
            },
        ]
    )
    registry = _FakeRegistry()
    result, trace = _agent(llm, registry).run("你是安全审计", "审阅代码")

    assert result == {"title": "SQL注入风险", "severity": "HIGH"}
    assert [name for name, _ in registry.calls] == ["code_knowledge_graph"]
    assert [t["tool"] for t in trace] == ["code_knowledge_graph"]


def test_react_loop_direct_final_answer():
    llm = _FakeLLM(
        [
            {
                "action": "final_answer",
                "final_text": json.dumps({"title": "无风险", "severity": "LOW"}),
            }
        ]
    )
    registry = _FakeRegistry()
    result, trace = _agent(llm, registry).run("你", "代码")

    assert result["title"] == "无风险"
    assert registry.calls == []  # 未调用任何工具（无需取证即直答）
    assert trace == []


def test_react_falls_back_when_steps_exhausted():
    # 全部决策都是调工具 → 步数耗尽仍无终答 → 回退到单次调用
    llm = _FakeLLM(
        [
            {"action": "call_tool", "tool_name": "code_knowledge_graph", "arguments": {}},
        ]
        * 2,  # max_steps=2
        fallback_text=json.dumps({"title": "回退结果"}),
    )
    agent = _agent(llm)
    agent._max_steps = 2
    result, _trace = agent.run("你", "代码")

    assert result == {"title": "回退结果"}
    assert llm.decision_calls == 2


def test_react_output_schema_validation():
    class Schema(BaseModel):
        title: str

    llm = _FakeLLM(
        [
            {
                "action": "final_answer",
                "final_text": json.dumps({"title": "由schema校验"}),
            }
        ]
    )
    # 传入 output_schema 时，结果应经过 model_dump
    result, _trace = _agent(llm).run("你", "代码", output_schema=Schema)
    assert result == {"title": "由schema校验"}


def test_react_rejects_disallowed_tool_and_recovers():
    llm = _FakeLLM(
        [
            {"action": "call_tool", "tool_name": "evil_tool", "arguments": {}},
            {
                "action": "final_answer",
                "final_text": json.dumps({"title": "ok"}),
            },
        ]
    )
    registry = _FakeRegistry()
    result, trace = _agent(llm, registry).run("你", "代码")

    assert result == {"title": "ok"}
    # 非法工具不应真正执行
    assert registry.calls == []
    # 非法工具不进入 trace
    assert trace == []