import { useEffect, useState } from 'react'
import { fetchLogs } from '../api/logs'
import { useLogStore } from '../store/logStore'
import { useResultStore } from '../store/resultStore'
import { selectTask, useTaskStore } from '../store/taskStore'
import type { ReviewTaskStatus } from '../store/status'

interface StatusPayload {
  status?: string
  taskId?: string
  riskSummary?: string
  errorCode?: string
}

const LAST_EVENT_ID_PREFIX = 'business-risk:last-event-id:'
const MAX_SEEN_EVENT_IDS = 512
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 15000

function toTaskStatus(status?: string): ReviewTaskStatus | null {
  if (status === 'PENDING') return 'PENDING'
  if (status === 'PROCESSING') return 'PROCESSING'
  if (status === 'SUCCESS') return 'SUCCESS'
  if (status === 'FAILED') return 'FAILED'
  if (status === 'HUMAN_REVIEW') return 'HUMAN_REVIEW'
  return null
}

function isTerminalStatus(status?: ReviewTaskStatus | null): boolean {
  return status === 'SUCCESS' || status === 'FAILED' || status === 'HUMAN_REVIEW' || status === 'SUCCEEDED' || status === 'NEED_REVIEW'
}

function safeParseJson<T>(value: string): T | null {
  try {
    return JSON.parse(value) as T
  } catch {
    return null
  }
}

function loadLastEventId(storageKey: string): string | null {
  try {
    const value = window.localStorage.getItem(storageKey)
    return value && value.trim() ? value : null
  } catch {
    return null
  }
}

function saveLastEventId(storageKey: string, eventId?: string): void {
  if (!eventId || !eventId.trim()) {
    return
  }
  try {
    window.localStorage.setItem(storageKey, eventId)
  } catch {
    // ignore storage failures
  }
}

function buildStreamUrl(sessionId: string, lastEventId?: string | null): string {
  const params = new URLSearchParams({ sessionId })
  if (lastEventId && lastEventId.trim()) {
    params.set('lastEventId', lastEventId)
  }
  return `/api/business-risk/stream?${params.toString()}`
}

export function useBusinessRiskSse(taskId: string | null, sessionIdOverride?: string) {
  const task = useTaskStore((state) => (taskId ? selectTask(taskId)(state) : undefined))
  const updateStatus = useTaskStore((state) => state.updateStatus)
  const setResult = useResultStore((state) => state.setResult)
  const setLogs = useLogStore((state) => state.setLogs)
  const [sseConnected, setSseConnected] = useState(false)

  useEffect(() => {
    if (!taskId) {
      setSseConnected(false)
      return
    }

    const sessionId = sessionIdOverride && sessionIdOverride.trim() ? sessionIdOverride : `session-${taskId}`
    const storageKey = `${LAST_EVENT_ID_PREFIX}${sessionId}:${taskId}`

    const seenEventIds = new Set<string>()
    const seenEventOrder: string[] = []

    async function refreshLogs() {
      if (!taskId) return
      try {
        const logs = await fetchLogs(taskId, task?.traceId)
        setLogs(taskId, logs)
      } catch {
        setLogs(taskId, [])
      }
    }

    let reconnectAttempt = 0
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    let source: EventSource | null = null
    let disposed = false
    let listeners: Array<{ type: string; listener: EventListener }> = []

    const rememberSeenEvent = (eventId?: string) => {
      if (!eventId || !eventId.trim()) {
        return
      }
      if (seenEventIds.has(eventId)) {
        return
      }

      seenEventIds.add(eventId)
      seenEventOrder.push(eventId)
      if (seenEventOrder.length > MAX_SEEN_EVENT_IDS) {
        const expired = seenEventOrder.shift()
        if (expired) {
          seenEventIds.delete(expired)
        }
      }
      saveLastEventId(storageKey, eventId)
    }

    const isDuplicateEvent = (eventId?: string) => {
      if (!eventId || !eventId.trim()) {
        return false
      }
      return seenEventIds.has(eventId)
    }

    const handleEvent = (eventType: string, event: MessageEvent) => {
      const eventId = typeof event.lastEventId === 'string' ? event.lastEventId.trim() : ''
      if (isDuplicateEvent(eventId)) {
        return
      }
      rememberSeenEvent(eventId)

      const statusPayload = safeParseJson<StatusPayload>(event.data)
      if (!statusPayload) return
      if (statusPayload.taskId && statusPayload.taskId !== taskId) return

      const status = toTaskStatus(statusPayload.status)
      if (status) {
        if (task && isTerminalStatus(task.status) && !isTerminalStatus(status)) {
          return
        }
        updateStatus(taskId, status)
      }

      if (eventType === 'task_completed') {
        setResult({
          taskId,
          riskScore: 0,
          riskBreakdown: [],
          needHumanReview: false,
          riskSummary: statusPayload.riskSummary ?? 'Business risk analysis completed',
        })
        void refreshLogs()
      }

      if (eventType === 'task_failed') {
        setResult({
          taskId,
          riskScore: 0,
          riskBreakdown: [],
          needHumanReview: false,
          errorCode: statusPayload.errorCode ?? 'BUSINESS_RISK_FAILED',
          errorMessage: 'Business risk analysis failed',
        })
        void refreshLogs()
      }

      if (eventType === 'task_human_review') {
        setResult({
          taskId,
          riskScore: 0,
          riskBreakdown: [],
          needHumanReview: true,
          riskSummary: statusPayload.riskSummary ?? 'Business risk analysis requires human review',
        })
        void refreshLogs()
      }
    }

    const clearConnection = () => {
      if (!source) {
        return
      }
      source.onopen = null
      source.onerror = null
      listeners.forEach(({ type, listener }) => source?.removeEventListener(type, listener))
      listeners = []
      source.close()
      source = null
    }

    const scheduleReconnect = () => {
      if (disposed || reconnectTimer) {
        return
      }
      const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttempt, RECONNECT_MAX_DELAY_MS)
      reconnectAttempt += 1
      const jitter = Math.floor(Math.random() * 250)
      reconnectTimer = setTimeout(() => {
        reconnectTimer = undefined
        connect()
      }, delay + jitter)
    }

    const connect = () => {
      if (disposed) {
        return
      }

      const storedLastEventId = loadLastEventId(storageKey)
      rememberSeenEvent(storedLastEventId ?? undefined)

      source = new EventSource(buildStreamUrl(sessionId, storedLastEventId))

      const addListener = (type: string, handler: (event: MessageEvent) => void) => {
        const listener = handler as EventListener
        listeners.push({ type, listener })
        source?.addEventListener(type, listener)
      }

      addListener('task_created', (event) => handleEvent('task_created', event))
      addListener('task_processing', (event) => handleEvent('task_processing', event))
      addListener('task_completed', (event) => handleEvent('task_completed', event))
      addListener('task_failed', (event) => handleEvent('task_failed', event))
      addListener('task_human_review', (event) => handleEvent('task_human_review', event))
      addListener('heartbeat', (event) => {
        const eventId = typeof event.lastEventId === 'string' ? event.lastEventId.trim() : ''
        rememberSeenEvent(eventId)
      })

      source.onopen = () => {
        reconnectAttempt = 0
        setSseConnected(true)
      }

      source.onerror = () => {
        if (disposed) {
          return
        }
        setSseConnected(false)
        clearConnection()
        scheduleReconnect()
      }
    }

    connect()

    return () => {
      disposed = true
      setSseConnected(false)
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
      }
      clearConnection()
    }
  }, [sessionIdOverride, setLogs, setResult, task, taskId, updateStatus])

  return { sseConnected }
}
