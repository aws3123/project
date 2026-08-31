import { useEffect } from 'react'
import { fetchLogs } from '../api/logs'
import { fetchTask, toReviewResultFromDetail } from '../api/task'
import { useTaskStore } from '../store/taskStore'
import { useResultStore } from '../store/resultStore'
import { useLogStore } from '../store/logStore'
import type { ReviewTaskStatus } from '../store/status'

const DEFAULT_INTERVAL = 5000
const MAX_INTERVAL = 30000

function nextInterval(current: number) {
  return Math.min(current * 1.5, MAX_INTERVAL)
}

function normalizeStatus(status: string): ReviewTaskStatus {
  if (status === 'QUEUED') return 'PENDING'
  if (status === 'PENDING') return 'PENDING'
  if (status === 'PROCESSING') return 'PROCESSING'
  if (status === 'SUCCESS') return 'SUCCESS'
  if (status === 'FAILED') return 'FAILED'
  if (status === 'HUMAN_REVIEW') return 'HUMAN_REVIEW'
  return 'PENDING'
}

export function useTaskPolling(taskId: string | null, traceId?: string, enabled = true) {
  const updateStatus = useTaskStore((state) => state.updateStatus)
  const setResult = useResultStore((state) => state.setResult)
  const setLogs = useLogStore((state) => state.setLogs)

  useEffect(() => {
    if (!taskId || !enabled) {
      return
    }

    const currentTaskId = taskId
    let cancelled = false
    let delay = DEFAULT_INTERVAL
    let timer: ReturnType<typeof setTimeout> | undefined

    async function poll() {
      if (cancelled) {
        return
      }

      try {
        const detail = await fetchTask(currentTaskId, traceId)
        const currentStatus = normalizeStatus(detail.task.status)
        updateStatus(currentTaskId, currentStatus)

        if (currentStatus === 'SUCCESS' || currentStatus === 'HUMAN_REVIEW' || currentStatus === 'FAILED') {
          const result = toReviewResultFromDetail(detail, currentTaskId)
          if (result) {
            setResult(result)
          }

          try {
            const logs = await fetchLogs(currentTaskId, traceId)
            setLogs(currentTaskId, logs)
          } catch {
            setLogs(currentTaskId, [])
          }
          return
        }
      } catch {
        // ignore and continue with backoff polling
      }

      timer = setTimeout(poll, delay)
      delay = nextInterval(delay)
    }

    void poll()

    return () => {
      cancelled = true
      if (timer) {
        clearTimeout(timer)
      }
    }
  }, [taskId, traceId, enabled, updateStatus, setResult, setLogs])
}
