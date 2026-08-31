import { useState, useCallback } from 'react'
import type { FeedbackType, FeedbackState } from '../types/feedback'
import { FEEDBACK_CATEGORIES } from '../types/feedback'
import { submitFeedback } from '../api/feedback'
import { getOrCreateTraceId } from '../utils/trace'

interface FeedbackWidgetProps {
  taskId: string
  sessionId: string
  source?: 'review' | 'business_risk'
  systemAnswer?: string
  className?: string
}

export function FeedbackWidget({ taskId, sessionId, source = 'review', systemAnswer, className = '' }: FeedbackWidgetProps) {
  const [state, setState] = useState<FeedbackState>({ submitted: false })
  const [selectedType, setSelectedType] = useState<FeedbackType | null>(null)
  const [category, setCategory] = useState<string>('')
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleTypeSelect = useCallback((type: FeedbackType) => {
    if (state.submitted) return
    setSelectedType(type)
  }, [state.submitted])

  const handleSubmit = useCallback(async () => {
    if (!selectedType || submitting) return

    setSubmitting(true)
    setError(null)

    try {
      const metadata = systemAnswer
        ? JSON.stringify({ systemAnswer })
        : undefined

      await submitFeedback({
        taskId,
        sessionId,
        feedbackType: selectedType,
        category: category || undefined,
        comment: comment || undefined,
        metadata,
        source,
      }, getOrCreateTraceId())

      setState({ submitted: true, type: selectedType, category, comment })
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交反馈失败')
    } finally {
      setSubmitting(false)
    }
  }, [selectedType, submitting, systemAnswer, taskId, sessionId, category, comment, source])

  if (state.submitted) {
    return (
      <div className={`feedback-widget ${className}`} data-testid="feedback-submitted">
        <p className="feedback-thanks">感谢反馈！</p>
      </div>
    )
  }

  return (
    <div className={`feedback-widget ${className}`} data-testid="feedback-widget">
      <div className="feedback-prompt">这个结果对您有帮助吗？</div>

      <div className="feedback-buttons">
        <button
          className={`feedback-btn${selectedType === 'thumbs_up' ? ' active up' : ''}`}
          onClick={() => handleTypeSelect('thumbs_up')}
          data-testid="feedback-thumbs-up"
          disabled={state.submitted}
        >
          👍 有帮助
        </button>
        <button
          className={`feedback-btn${selectedType === 'thumbs_down' ? ' active down' : ''}`}
          onClick={() => handleTypeSelect('thumbs_down')}
          data-testid="feedback-thumbs-down"
          disabled={state.submitted}
        >
          👎 没帮助
        </button>
      </div>

      {selectedType && (
        <div className="feedback-detail" data-testid="feedback-detail">
          <select
            className="feedback-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            data-testid="feedback-category"
          >
            <option value="">选择分类（可选）</option>
            {FEEDBACK_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>

          <textarea
            className="feedback-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="补充意见（可选）"
            rows={3}
            data-testid="feedback-comment"
          />

          <button
            className="feedback-submit-btn"
            onClick={handleSubmit}
            disabled={submitting}
            data-testid="feedback-submit-btn"
          >
            {submitting ? '提交中…' : '提交反馈'}
          </button>

          {error && <p className="error-text" data-testid="feedback-error">{error}</p>}
        </div>
      )}
    </div>
  )
}
