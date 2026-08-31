import { describe, it, expect, beforeEach, vi } from 'vitest'

import { fetchLogs } from '../api/logs'
import { getLastLogRequest, resetCapturedRequests } from './msw/handlers'

describe('fetchLogs', () => {
  beforeEach(() => {
    resetCapturedRequests()
    vi.stubEnv('VITE_API_KEY', 'test-api-key')
  })

  it('requests backend logs endpoint and maps payload', async () => {
    const logs = await fetchLogs('task_mock_1', 'trace-test-1')

    expect(logs).toEqual([
      {
        node: 'diff',
        status: 'SUCCESS',
        durationMs: 12,
        inputSummary: 'input mock',
        outputSummary: 'output mock',
        timestamp: '2026-04-18T00:00:00.000Z',
      },
    ])

    const captured = getLastLogRequest()
    expect(captured).toEqual({ taskId: 'task_mock_1', traceId: 'trace-test-1' })
  })
})
