"""审查结果交接路由 —— 处理 AI 审查结果的人工交接流程。

什么是 Handoff（交接）？
  当 AI 审查发现高风险问题时，需要人工复核。
  "交接"就是 AI 把审查结果"移交"给人类审查员的过程。
  人类审查员可以：
  - 查看 AI 的审查报告
  - 做出决定（approve=通过、reject=拒绝、comment=评论）
  - 将决定回传给系统

本模块提供两个接口：
  GET  /ai/handoff/{task_id}  → 获取交接信息（任务状态 + 报告 URL）
  POST /ai/handoff/{task_id}  → 提交人工复核决定
"""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_result_service, get_task_service
from schemas.api.request import HandoffRequest

router = APIRouter()


@router.get("/review/handoff/{task_id}")
@router.get("/handoff/{task_id}")
def get_handoff(
    task_id: str,
    result_service=Depends(get_result_service),  # 结果服务
    task_service=Depends(get_task_service),       # 任务服务
):
    """获取交接信息 —— 返回任务状态和报告 URL。

    前端需要知道：
      1. 任务是否已完成
      2. 审查报告在哪里（reportUrl）

    参数：
        task_id: 任务 ID（URL 路径参数）
    返回：
        包含 taskId、status、reportUrl 的字典
    """
    task = task_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    result = result_service.get(task_id)
    return {
        "taskId": task.id,
        "status": task.status,
        "reportUrl": result.reportUrl if result else None,
    }


@router.post("/review/handoff/{task_id}")
def submit_handoff(
    task_id: str,
    request: HandoffRequest,          # 交接请求体（包含决定、操作人、评论）
    task_service=Depends(get_task_service),
):
    """提交人工复核决定。

    人类审查员通过此接口提交自己的判断：
      - decision: 决定（如 approve/reject）
      - operator: 操作人（谁做的决定）
      - comment: 评论（补充说明）

    参数：
        task_id: 任务 ID
        request: 交接请求体
    返回：
        更新后的任务信息（包含交接详情）
    """
    task = task_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        updated = task_service.handle_handoff(
            task_id,
            decision=request.decision,
            operator=request.operator,
            comment=request.comment,
        )
    except ValueError as exc:
        # 409 Conflict：任务状态不允许此操作（如已完成的任务不能再改）
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "taskId": updated.id,
        "status": updated.status,
        "handoff": updated.payload.get("handoff", {}),
    }
"""Endpoints handling AI-generated review handoff to other services."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_result_service, get_task_service
from schemas.api.request import HandoffRequest

router = APIRouter()


@router.get("/review/handoff/{task_id}")
@router.get("/handoff/{task_id}")
def get_handoff(task_id: str, result_service=Depends(get_result_service), task_service=Depends(get_task_service)):
    task = task_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    result = result_service.get(task_id)
    return {
        "taskId": task.id,
        "status": task.status,
        "reportUrl": result.reportUrl if result else None,
    }


@router.post("/review/handoff/{task_id}")
def submit_handoff(task_id: str, request: HandoffRequest, task_service=Depends(get_task_service)):
    task = task_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        updated = task_service.handle_handoff(
            task_id,
            decision=request.decision,
            operator=request.operator,
            comment=request.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "taskId": updated.id,
        "status": updated.status,
        "handoff": updated.payload.get("handoff", {}),
    }
