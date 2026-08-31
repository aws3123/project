import type { ReviewTaskStatus } from '../store/status'

const timelineSteps = [
  { key: 'PENDING', label: '排队中' },
  { key: 'PROCESSING', label: '处理中' },
  { key: 'HUMAN_REVIEW', label: '人工复核' },
  { key: 'SUCCESS', label: '完成' },
] as const

function normalizeStatus(status?: ReviewTaskStatus) {
  if (!status) return 'PENDING'
  if (status === 'QUEUED') return 'PENDING'
  if (status === 'NEED_REVIEW') return 'HUMAN_REVIEW'
  if (status === 'SUCCEEDED') return 'SUCCESS'
  return status
}

function getStepIndex(status?: ReviewTaskStatus) {
  const normalized = normalizeStatus(status)
  const index = timelineSteps.findIndex((step) => step.key === normalized)
  if (index >= 0) {
    return index
  }
  if (normalized === 'FAILED') {
    return 1
  }
  return 0
}

interface TaskStatusTimelineProps {
  status?: ReviewTaskStatus
  sseStateText?: string
  failedMessage?: string
}

export function TaskStatusTimeline({ status, sseStateText, failedMessage }: TaskStatusTimelineProps) {
  const currentStepIndex = getStepIndex(status)
  const isFailed = status === 'FAILED'

  return (
    <div className="panel status-timeline-panel">
      <h3>执行进度</h3>
      <ol className="status-timeline">
        {timelineSteps.map((step, index) => {
          const isDone = index <= currentStepIndex
          const isCurrent = index === currentStepIndex
          return (
            <li key={step.key} className={`timeline-item${isDone ? ' done' : ''}${isCurrent ? ' current' : ''}`}>
              <span className="timeline-dot" />
              <span>{step.label}</span>
            </li>
          )
        })}
      </ol>
      {sseStateText && (
        <p className="page-desc" data-testid="business-risk-sse-state">
          {sseStateText}
        </p>
      )}
      {isFailed && failedMessage && (
        <p className="error-text">{failedMessage}</p>
      )}
    </div>
  )
}
