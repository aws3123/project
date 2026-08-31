import type { ReviewTaskStatus } from '../store/status'
import type {
  HandoffDecision,
  HandoffRequest,
  ReviewResult,
  ReviewTask,
  TaskDetailResponse,
} from '../types/review'
import { http } from './client'

function isHandoffDecision(value?: string): value is HandoffDecision {
  return value === 'APPROVED' || value === 'REJECTED' || value === 'CHANGES_REQUESTED'
}

function mapStatus(status?: string, fallback: ReviewTaskStatus = 'PENDING'): ReviewTaskStatus {
  if (!status) {
    return fallback
  }

  if (status === 'QUEUED') return 'QUEUED'
  if (status === 'PENDING') return 'PENDING'
  if (status === 'PROCESSING') return 'PROCESSING'
  if (status === 'SUCCESS') return 'SUCCESS'
  if (status === 'FAILED') return 'FAILED'
  if (status === 'HUMAN_REVIEW') return 'HUMAN_REVIEW'

  return fallback
}

function mapMode(mode?: string): ReviewTask['mode'] {
  if (!mode) return undefined
  const normalized = mode.toLowerCase()
  if (normalized === 'sync' || normalized === 'async') {
    return normalized
  }
  if (normalized === 'business_risk_source') {
    return 'business_risk_source'
  }
  return undefined
}

export function toReviewTaskFromDetail(
  detail: TaskDetailResponse,
  fallbackTaskId: string,
  previous?: ReviewTask,
): ReviewTask {
  const task = detail.task
  const taskId = task.taskId ?? previous?.taskId ?? fallbackTaskId

  return {
    taskId,
    projectId: task.projectId ?? previous?.projectId ?? '',
    projectName: task.projectName ?? previous?.projectName,
    prLink: task.prUrl ?? previous?.prLink,
    diffContent: previous?.diffContent,
    mode: mapMode(task.mode) ?? previous?.mode,
    status: mapStatus(task.status, previous?.status ?? 'PENDING'),
    createdAt: task.createdAt ?? previous?.createdAt ?? new Date().toISOString(),
    updatedAt: task.updatedAt ?? previous?.updatedAt,
    sessionId: previous?.sessionId,
    traceId: task.traceId ?? previous?.traceId,
    handoffDecision: isHandoffDecision(task.handoffDecision) ? task.handoffDecision : previous?.handoffDecision,
    handoffOperator: task.handoffOperator ?? previous?.handoffOperator,
    handoffComment: task.handoffComment ?? previous?.handoffComment,
    handoffHandledAt: task.handoffHandledAt ?? previous?.handoffHandledAt,
  }
}

export function toReviewResultFromDetail(detail: TaskDetailResponse, fallbackTaskId: string): ReviewResult | undefined {
  if (!detail.result) {
    return undefined
  }

  return {
    taskId: detail.task.taskId ?? fallbackTaskId,
    riskScore: detail.result.riskScore ?? 0,
    riskBreakdown: [],
    needHumanReview: detail.result.needHumanReview ?? false,
    riskSummary: detail.result.riskSummary,
    errorCode: detail.result.errorCode,
    errorMessage: detail.result.errorMessage,
  }
}

export function fetchTask(taskId: string, traceId?: string) {
  return http<TaskDetailResponse>(`/api/review/tasks/${taskId}`, { traceId })
}

export interface TaskListParams {
  page?: number
  size?: number
  projectId?: string
  status?: string
}

export interface TaskListItem {
  taskId?: string
  projectId: string
  projectName?: string
  status: string
  mode?: string
  prUrl?: string
  createdAt?: string
  updatedAt?: string
}

export interface TaskListResponse {
  items: TaskListItem[]
  total: number
  page: number
  size: number
  totalPages: number
}

export function fetchTaskList(params: TaskListParams = {}, traceId?: string) {
  const query = new URLSearchParams()
  if (params.page) query.set('page', String(params.page))
  if (params.size) query.set('size', String(params.size))
  if (params.projectId) query.set('projectId', params.projectId)
  if (params.status) query.set('status', params.status)
  const qs = query.toString()
  return http<TaskListResponse>(`/api/review/tasks${qs ? '?' + qs : ''}`, { traceId })
}

export function submitHandoff(taskId: string, payload: HandoffRequest, traceId?: string) {
  return http<TaskDetailResponse>(`/api/review/handoff/${taskId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
    traceId,
  })
}
