from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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

    def run(self, payload: dict, context: ToolContext) -> ToolResult:
        ...
