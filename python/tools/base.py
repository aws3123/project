from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class ToolResult:
    name: str
    payload: dict
    metadata: dict | None = None


@dataclass(slots=True)
class ToolContext:
    task_id: str
    metadata: dict | None = None


class Tool(Protocol):
    name: str
    # 可选元数据：供 ReAct 等自主决策场景向 LLM 描述工具用途与入参。
    description: str = ""
    parameters: dict[str, Any] | None = None

    def run(self, payload: dict, context: ToolContext) -> ToolResult: ...
