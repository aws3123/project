import type { FeedbackSubmitRequest, FeedbackSubmitResponse } from '../types/feedback'
import { http } from './client'

export function submitFeedback(payload: FeedbackSubmitRequest, traceId?: string) {
  return http<FeedbackSubmitResponse>('/api/feedback/submit', {
    method: 'POST',
    body: JSON.stringify(payload),
    traceId,
  })
}
