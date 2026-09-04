import type { ReviewStepProgress } from '../types/review'

interface ReviewProgressPanelProps {
  steps: ReviewStepProgress[]
  active: boolean
}

const STATUS_LABELS: Record<ReviewStepProgress['status'], string> = {
  RUNNING: '进行中…',
  SUCCEEDED: '完成',
  FAILED: '失败',
}

/** 流式同步审查的进度时间线：实时展示每个审查步骤的执行状态与耗时 */
export function ReviewProgressPanel({ steps, active }: ReviewProgressPanelProps) {
  if (!active || steps.length === 0) {
    return null
  }

  return (
    <div className="review-progress" aria-live="polite">
      <h4>审查进度</h4>
      <ol className="progress-steps">
        {steps.map((step) => (
          <li key={step.step} className={`progress-step ${step.status.toLowerCase()}`}>
            <span className="step-name">{step.step}</span>
            <span className="step-status">
              {STATUS_LABELS[step.status]}
              {step.status !== 'RUNNING' && step.durationMs != null ? `（${step.durationMs}ms）` : ''}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
