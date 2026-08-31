import type { ReviewTaskStatus } from '../store/status'

export type HandoffDecision = 'APPROVED' | 'REJECTED' | 'CHANGES_REQUESTED'
export type SubmissionMode = 'sync' | 'async' | 'auto'
export type ResolvedSubmissionMode = 'sync' | 'async'
export type BackendReviewMode = 'SYNC' | 'ASYNC'
export type DispatchRoute = 'SYNC' | 'ASYNC'

export interface ReviewTaskPayload {
  projectId: string
  projectName: string
  prLink: string
  diffContent: string
  question: string
  mode: SubmissionMode
}

export interface ReviewTask {
  taskId: string
  projectId: string
  projectName?: string
  prLink?: string
  diffContent?: string
  mode?: SubmissionMode | 'business_risk_source'
  status: ReviewTaskStatus
  createdAt: string
  updatedAt?: string
  sessionId?: string
  traceId?: string
  handoffDecision?: HandoffDecision
  handoffOperator?: string
  handoffComment?: string
  handoffHandledAt?: string
}

export interface ReviewRiskBreakdownItem {
  dimension: 'impact' | 'sql' | 'api' | 'cache' | 'config' | 'tests' | 'history'
  score: number
  description: string
}

export interface ReviewResult {
  taskId: string
  riskScore: number
  riskBreakdown: ReviewRiskBreakdownItem[]
  needHumanReview: boolean
  riskSummary?: string
  details?: string[]
  errorCode?: string
  errorMessage?: string
  reportUrl?: string
}

export interface BackendReviewSyncRequest {
  projectId: string
  projectName: string
  prUrl: string
  diffContent: string
  mode: BackendReviewMode
}

export interface BackendReviewSyncResponse {
  taskId: string
  riskScore: number
  riskSummary: string
  needHumanReview: boolean
  details: string[]
}

export interface BackendReviewAsyncResponse {
  taskId: string
  status: string
}

export interface BackendReviewDispatchRequest {
  projectId: string
  projectName: string
  prUrl: string
  diffContent: string
  question: string
}

export interface BackendReviewDispatchResponse {
  route: DispatchRoute
  taskId: string
  status: string
  dispatchReason: string
  confidence: number
  usedLightweightClassifier: boolean
  result?: BackendReviewSyncResponse
}

export type SubmissionOutcome =
  | { sourceMode: 'sync'; resolvedMode: 'sync'; result: ReviewResult }
  | { sourceMode: 'async'; resolvedMode: 'async'; taskId: string }
  | { sourceMode: 'auto'; resolvedMode: 'sync'; result: ReviewResult }
  | { sourceMode: 'auto'; resolvedMode: 'async'; taskId: string }

export interface TaskDetailResponse {
  task: {
    taskId: string
    projectId: string
    projectName?: string
    status: string
    mode?: string
    prUrl?: string
    traceId?: string
    handoffDecision?: string
    handoffOperator?: string
    handoffComment?: string
    handoffHandledAt?: string
    createdAt?: string
    updatedAt?: string
  }
  result?: {
    riskScore?: number
    riskSummary?: string
    needHumanReview?: boolean
    errorCode?: string
    errorMessage?: string
    createdAt?: string
  } | null
}

export interface HandoffRequest {
  decision: HandoffDecision
  operator?: string
  comment?: string
}

export interface ReviewLogEntry {
  node: string
  status: 'SUCCESS' | 'FAILED' | 'RETRIED'
  durationMs: number
  inputSummary: string
  outputSummary: string
  timestamp: string
}
