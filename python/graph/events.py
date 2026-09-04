"""
流式事件模块 —— 同步审查的 SSE 事件契约
======================================

定义 GraphRunner 在流式模式下对外发送的事件类型与构造器。
事件经 EventSink 投递到路由层的异步队列，最终以 SSE 帧推给 Java 网关。

设计原则：
1. 事件管道的故障绝不影响审查执行本身（_emit 吞掉所有发送异常）
2. 事件词汇表对齐 AG-UI 协议的简化版：
   run_started / step_started / step_finished / run_finished / run_error / heartbeat
3. run_finished 携带的 result 与旧同步接口的 JSON 响应完全一致，
   Java 落库逻辑与前端映射零改动
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# 事件接收器：工作线程内调用，实现方负责线程安全投递
EventSink = Callable[[dict[str, Any]], None]

# 终态事件：路由层收到后 drain 队列并关闭流
TERMINAL_EVENTS = frozenset({"run_finished", "run_error"})


def format_sse_frame(event: dict[str, Any]) -> str:
    """将事件 dict 序列化为 SSE 帧（event + data 两行）。

    注意：不生成 id 字段——由 Java 网关转发时统一按 taskId 维度重新编号，
    这样跨语言两侧不需要维护同一个计数器。
    """
    event_name = event.get("event", "message")
    # data 统一为一行 JSON（SSE 的 data 不允许裸换行）
    payload = json.dumps(event.get("data", {}), ensure_ascii=False, default=str)
    return f"event: {event_name}\ndata: {payload}\n\n"


def format_heartbeat_frame() -> str:
    """心跳帧：真实事件（非注释行），确保 Java WebClient 的 SSE 解码器能收到。"""
    return "event: heartbeat\ndata: {}\n\n"


def _emit(sink: EventSink | None, event: str, data: dict[str, Any]) -> None:
    """线程安全地发送事件；sink 为空或发送失败时静默降级（不影响审查执行）。"""
    if sink is None:
        return
    try:
        sink({"event": event, "data": data})
    except Exception:
        logger.warning(
            "event sink failed for %s, streaming degraded", event, exc_info=True
        )


def emit_run_started(sink: EventSink | None, task_id: str, total_steps: int) -> None:
    _emit(sink, "run_started", {"taskId": task_id, "totalSteps": total_steps})


def emit_step_started(sink: EventSink | None, task_id: str, step: str) -> None:
    _emit(sink, "step_started", {"taskId": task_id, "step": step})


def emit_step_finished(
    sink: EventSink | None,
    task_id: str,
    step: str,
    status: str,
    duration_ms: int,
) -> None:
    _emit(
        sink,
        "step_finished",
        {
            "taskId": task_id,
            "step": step,
            "status": status,
            "durationMs": duration_ms,
        },
    )


def emit_run_finished(sink: EventSink | None, task_id: str, result: Any) -> None:
    """result 为 ReviewResult（pydantic），序列化行为与旧同步接口的响应一致。"""
    if hasattr(result, "model_dump_json"):
        result_payload = json.loads(result.model_dump_json())
    else:
        result_payload = result
    _emit(sink, "run_finished", {"taskId": task_id, "result": result_payload})


def emit_run_error(
    sink: EventSink | None, task_id: str, error_code: str, error_message: str
) -> None:
    _emit(
        sink,
        "run_error",
        {"taskId": task_id, "errorCode": error_code, "errorMessage": error_message},
    )
