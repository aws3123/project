import { useState } from 'react'
import type { ReviewTaskPayload, SubmissionMode, SubmissionOutcome } from '../types/review'
import { submitAsync, submitDispatch, submitSync, toSubmissionOutcomeFromDispatch } from '../api/review'
import { getOrCreateTraceId } from '../utils/trace'

export function useReviewSubmission() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const traceId = getOrCreateTraceId()

  async function submit(payload: ReviewTaskPayload, mode: SubmissionMode): Promise<SubmissionOutcome> {
    try {
      setError(null)
      setLoading(true)
      const finalPayload: ReviewTaskPayload = { ...payload, mode }

      if (mode === 'sync') {
        const result = await submitSync(finalPayload, traceId)
        return { sourceMode: 'sync', resolvedMode: 'sync', result }
      }

      if (mode === 'async') {
        const asyncResponse = await submitAsync(finalPayload, traceId)
        return { sourceMode: 'async', resolvedMode: 'async', taskId: asyncResponse.taskId }
      }

      const dispatchResponse = await submitDispatch(finalPayload, traceId)
      return toSubmissionOutcomeFromDispatch(dispatchResponse)
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败')
      throw err
    } finally {
      setLoading(false)
    }
  }

  return { submit, loading, error, traceId }
}
