export type ReviewTaskStatus =
  | 'QUEUED'
  | 'PENDING'
  | 'PROCESSING'
  | 'SUCCEEDED'
  | 'SUCCESS'
  | 'FAILED'
  | 'NEED_REVIEW'
  | 'HUMAN_REVIEW'

export const statusLabelMap: Record<ReviewTaskStatus, string> = {
  QUEUED: '排队中',
  PENDING: '排队中',
  PROCESSING: '处理中',
  SUCCEEDED: '已完成',
  SUCCESS: '已完成',
  FAILED: '失败',
  NEED_REVIEW: '待人工复核',
  HUMAN_REVIEW: '待人工复核',
}
