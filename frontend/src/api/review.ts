import type {
  BackendReviewAsyncResponse,
  BackendReviewDispatchRequest,
  BackendReviewDispatchResponse,
  BackendReviewSyncRequest,
  BackendReviewSyncResponse,
  ReviewResult,
  ReviewTaskPayload,
  SubmissionOutcome,
} from '../types/review'
import { http } from './client'

const SYNC_ENDPOINT = '/api/review/sync'
const ASYNC_ENDPOINT = '/api/review/async'
const DISPATCH_ENDPOINT = '/api/review/dispatch'

function toBackendMode(mode: ReviewTaskPayload['mode']): BackendReviewSyncRequest['mode'] {
  return mode === 'sync' ? 'SYNC' : 'ASYNC'
}

function toBackendPayload(payload: ReviewTaskPayload): BackendReviewSyncRequest {
  return {
    projectId: payload.projectId,
    projectName: payload.projectName,
    prUrl: payload.prLink,
    diffContent: payload.diffContent,
    mode: toBackendMode(payload.mode),
  }
}

function toReviewResult(payload: BackendReviewSyncResponse): ReviewResult {
  return {
    taskId: payload.taskId,
    riskScore: payload.riskScore,
    riskBreakdown: [],
    needHumanReview: payload.needHumanReview,
    riskSummary: payload.riskSummary,
    details: payload.details,
  }
}

function toDispatchPayload(payload: ReviewTaskPayload): BackendReviewDispatchRequest {
  return {
    projectId: payload.projectId,
    projectName: payload.projectName,
    prUrl: payload.prLink,
    diffContent: payload.diffContent,
    question: payload.question,
  }
}

export function toSubmissionOutcomeFromDispatch(response: BackendReviewDispatchResponse): SubmissionOutcome {
  if (response.route === 'SYNC' && response.result) {
    return {
      sourceMode: 'auto',
      resolvedMode: 'sync',
      result: toReviewResult(response.result),
    }
  }

  return {
    sourceMode: 'auto',
    resolvedMode: 'async',
    taskId: response.taskId,
  }
}

export async function submitSync(payload: ReviewTaskPayload, traceId?: string) {
  const response = await http<BackendReviewSyncResponse>(SYNC_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(toBackendPayload(payload)),
    traceId,
  })
  return toReviewResult(response)
}

export function submitAsync(payload: ReviewTaskPayload, traceId?: string) {
  return http<BackendReviewAsyncResponse>(ASYNC_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(toBackendPayload(payload)),
    traceId,
  })
}

export function submitDispatch(payload: ReviewTaskPayload, traceId?: string) {
  return http<BackendReviewDispatchResponse>(DISPATCH_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(toDispatchPayload(payload)),
    traceId,
  })
}
