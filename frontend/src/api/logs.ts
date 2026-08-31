import type { ReviewLogEntry } from '../types/review'
import { http } from './client'

const LOGS_ENDPOINT = '/api/review/logs'

interface BackendReviewLogEntry {
  node: string
  status: string
  durationMs?: number
  input?: unknown
  output?: unknown
  message?: unknown
  timestamp: string
}

function toString(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function toReviewLogEntry(entry: BackendReviewLogEntry): ReviewLogEntry {
  const normalizedStatus = entry.status === 'FAILED' || entry.status === 'RETRIED' ? entry.status : 'SUCCESS'
  const detail = toString(entry.message)

  return {
    node: entry.node,
    status: normalizedStatus,
    durationMs: entry.durationMs ?? 0,
    inputSummary: toString(entry.input) || detail,
    outputSummary: toString(entry.output) || detail,
    timestamp: entry.timestamp,
  }
}

export async function fetchLogs(taskId: string, traceId?: string): Promise<ReviewLogEntry[]> {
  const response = await http<BackendReviewLogEntry[]>(`${LOGS_ENDPOINT}/${taskId}`, { traceId })
  return response.map(toReviewLogEntry)
}
