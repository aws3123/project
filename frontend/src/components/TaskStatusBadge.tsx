import type { ReviewTaskStatus } from '../store/status'
import { statusLabelMap } from '../store/status'

interface TaskStatusBadgeProps {
  status: ReviewTaskStatus
}

export function TaskStatusBadge({ status }: TaskStatusBadgeProps) {
  return (
    <span className={`status-badge status-${status.toLowerCase()}`}>
      <span className="status-badge-dot" aria-hidden="true" />
      {statusLabelMap[status]}
    </span>
  )
}
