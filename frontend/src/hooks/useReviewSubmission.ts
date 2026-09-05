import { useState } from 'react'
import type {
  ReviewStepProgress,
  ReviewStreamProgressEvent,
  ReviewTaskPayload,
  SubmissionMode,
  SubmissionOutcome,
} from '../types/review'
import { submitAsync, submitDispatch, submitSync, submitSyncStream, toSubmissionOutcomeFromDispatch } from '../api/review'
import { getOrCreateTraceId } from '../utils/trace'

/** 流式传输回滚开关：设置 VITE_SYNC_TRANSPORT=blocking 时走旧的一次性阻塞请求 */
function isStreamTransport(): boolean {
  return import.meta.env.VITE_SYNC_TRANSPORT !== 'blocking'
}

/** 将流式进度事件合并进步骤时间线（step_started 新增 RUNNING，step_finished 更新状态） */
function upsertStep(steps: ReviewStepProgress[], progress: ReviewStreamProgressEvent): ReviewStepProgress[] {
  if (progress.event === 'step_started') {
    const existing = steps.find((s) => s.step === progress.step)
    if (existing) {
      return steps.map((s) => (s.step === progress.step ? { ...s, status: 'RUNNING' as const } : s))
    }
    return [...steps, { step: progress.step, status: 'RUNNING' }]
  }
  if (progress.event === 'step_finished') {
    return steps.map((s) =>
      s.step === progress.step
        ? { ...s, status: progress.status, durationMs: progress.durationMs }
        : s,
    )
  }
  return steps
}

export function useReviewSubmission() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [steps, setSteps] = useState<ReviewStepProgress[]>([])
  const traceId = getOrCreateTraceId()

  async function submit(payload: ReviewTaskPayload, mode: SubmissionMode): Promise<SubmissionOutcome> {
    try {
      setError(null)
      setLoading(true)
      setSteps([])
      const finalPayload: ReviewTaskPayload = { ...payload, mode }

      if (mode === 'sync') {
        if (isStreamTransport()) {
          const result = await submitSyncStream(
            finalPayload,
            (progress) => setSteps((prev) => upsertStep(prev, progress)),
            traceId,
          )
          return { sourceMode: 'sync', resolvedMode: 'sync', result }
        }
        // 回滚通道：旧的一次性阻塞请求（无进度展示）
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

  return { submit, loading, error, steps, traceId }
}
