"""Node-local working copies and explicit LangGraph state updates."""

from copy import deepcopy
from typing import Any


def node_input(state: dict[str, Any]) -> dict[str, Any]:
    """Isolate nested inputs and collect only this node's new tool logs."""
    working = deepcopy(state)
    working["tool_logs"] = []
    return working


def node_output(state: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Publish owned fields, never a copy of the entire shared state."""
    update = {key: state[key] for key in keys if key in state}
    if state.get("tool_logs"):
        update["tool_logs"] = state["tool_logs"]
    return update


def merge_node_status(
    previous: dict[str, str], update: dict[str, str]
) -> dict[str, str]:
    return {**previous, **update}
