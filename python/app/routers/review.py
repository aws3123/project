from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.dependencies import (
    get_ai_service,
    get_log_service,
    get_result_service,
    get_task_service,
    get_trace_id,
)
from schemas.backend_contract import parse_sync_payload
from schemas.result import ReviewResult

router = APIRouter()

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
    return ai_service.run(request)


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
