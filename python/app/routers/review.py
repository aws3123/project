from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.dependencies import (
    get_ai_service,
    get_log_service,
    get_result_service,
    get_task_service,
    get_trace_id,
)
from graph.events import (
    TERMINAL_EVENTS,
    format_heartbeat_frame,
    format_sse_frame,
)
from schemas.api.backend_contract import parse_sync_payload
from schemas.api.result import ReviewResult
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 心跳间隔（秒）：队列空闲期间定期发送，防止网关/LB 空闲超时切断长连接
STREAM_HEARTBEAT_SECONDS = 15.0


def _swallow_task_exception(task: asyncio.Task) -> None:
    """消费后台任务的异常，避免 asyncio "exception never retrieved" 告警。"""
    if not task.cancelled():
        task.exception()


@router.post("/review/sync", response_model=ReviewResult)
async def review_sync(
    payload: dict,
    ai_service=Depends(get_ai_service),
    trace_id: str = Depends(get_trace_id),
):
    try:
        request = parse_sync_payload(payload, trace_id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    # 阻塞的全流水线执行移入线程池，避免卡死事件循环
    # （旧实现直接在 async 路由内同步执行，期间健康检查等所有请求都会排队）
    return await asyncio.to_thread(ai_service.run, request)


@router.post("/review/sync/stream")
async def review_sync_stream(
    payload: dict,
    ai_service=Depends(get_ai_service),
    trace_id: str = Depends(get_trace_id),
):
    """流式同步审查：SSE 逐事件推送审查进度，终态事件携带完整结果。

    事件序列：run_started → step_started/step_finished(每节点) →
    run_finished(含 result) 或 run_error；空闲期间发送 heartbeat。
    run_finished 中的 result 与旧同步接口的响应契约完全一致。
    """
    try:
        request = parse_sync_payload(payload, trace_id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def sink(event: dict) -> None:
        """事件接收器：工作线程内调用，线程安全地投递到事件循环。"""
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def run_pipeline() -> None:
        try:
            await asyncio.to_thread(ai_service.run, request, sink)
        except Exception:
            # run_error 已由 runner 经 sink 发出；此处仅记录，避免
            # 后台 task 的异常无人消费
            logger.exception("stream pipeline failed taskId=%s", request.taskId)

    task = asyncio.create_task(run_pipeline())

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=STREAM_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield format_heartbeat_frame()
                    continue
                yield format_sse_frame(event)
                if event.get("event") in TERMINAL_EVENTS:
                    # 终态：drain 队列中残余事件后正常收尾
                    while not queue.empty():
                        rest = queue.get_nowait()
                        if isinstance(rest, dict):
                            yield format_sse_frame(rest)
                    return
        finally:
            if not task.done():
                # 客户端提前断开：工作线程继续跑完（P1 不做协作取消），
                # 审查结果照常产出；流端仅记日志
                logger.info("stream client disconnected early taskId=%s", request.taskId)
                task.add_done_callback(_swallow_task_exception)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # 关键：禁用 Nginx 等反向代理的响应缓冲，否则流式退化为攒包转发
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/review/tasks/{task_id}")
def get_task(task_id: str, task_service=Depends(get_task_service), result_service=Depends(get_result_service)):
    task = task_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    result = result_service.get(task_id)
    return {"task": task, "result": result}


@router.get("/review/logs/{task_id}")
def get_logs(task_id: str, log_service=Depends(get_log_service)):
    logs = log_service.list_by_task(task_id)
    if not logs:
        raise HTTPException(status_code=404, detail="Logs not found")
    return logs
