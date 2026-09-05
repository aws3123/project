import type {
  FeedbackExportResponse,
  FeedbackStatsResponse,
  FeedbackSubmitRequest,
  FeedbackSubmitResponse,
} from '../types/feedback'
import { http } from './client'

export function submitFeedback(payload: FeedbackSubmitRequest, traceId?: string) {
  return http<FeedbackSubmitResponse>('/api/feedback/submit', {
    method: 'POST',
    body: JSON.stringify(payload),
    traceId,
  })
}

export interface FeedbackStatsParams {
  from: Date
  to: Date
  source?: 'review' | 'business_risk'
}

export function fetchFeedbackStats(params: FeedbackStatsParams, traceId?: string) {
  const query = new URLSearchParams()
  query.set('from', params.from.toISOString())
  query.set('to', params.to.toISOString())
  if (params.source) query.set('source', params.source)
  return http<FeedbackStatsResponse>(`/api/feedback/stats?${query.toString()}`, { traceId })
}

export interface FeedbackExportParams extends FeedbackStatsParams {
  page?: number
  size?: number
}

export function fetchFeedbackExport(params: FeedbackExportParams, traceId?: string) {
  const query = new URLSearchParams()
  query.set('from', params.from.toISOString())
  query.set('to', params.to.toISOString())
  if (params.source) query.set('source', params.source)
  query.set('page', String(params.page ?? 1))
  query.set('size', String(params.size ?? 10))
  return http<FeedbackExportResponse>(`/api/feedback/export?${query.toString()}`, { traceId })
}
