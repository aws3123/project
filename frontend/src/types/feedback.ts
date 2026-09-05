export type FeedbackType = 'thumbs_up' | 'thumbs_down'

export type FeedbackCategory =
  | '结果准确'
  | '结果不准确'
  | '遗漏风险'
  | '误报'
  | '其他'

export interface FeedbackSubmitRequest {
  taskId: string
  sessionId: string
  feedbackType: FeedbackType
  category?: FeedbackCategory | string
  comment?: string
  metadata?: string
  source?: 'review' | 'business_risk'
}

export interface FeedbackSubmitResponse {
  id: number
  status: 'accepted'
}

export interface FeedbackState {
  submitted: boolean
  type?: FeedbackType
  category?: string
  comment?: string
}

export interface FeedbackStatsResponse {
  total: number
  thumbs_up: number
  thumbs_down: number
  ratio: string
  daily_breakdown: Array<{
    date: string
    thumbs_up: number
    thumbs_down: number
  }>
}

export interface FeedbackExportItem {
  id: number
  taskId: string
  sessionId: string
  feedbackType: FeedbackType
  category?: string | null
  comment?: string | null
  metadata?: string | null
  userAgent?: string | null
  source?: string | null
  traceId?: string | null
  createdAt: string
}

export interface FeedbackExportResponse {
  records: FeedbackExportItem[]
  total: number
  size: number
  current: number
  pages: number
}

export const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: '结果准确', label: '结果准确' },
  { value: '结果不准确', label: '结果不准确' },
  { value: '遗漏风险', label: '遗漏了风险' },
  { value: '误报', label: '误报/非风险' },
  { value: '其他', label: '其他' },
]
