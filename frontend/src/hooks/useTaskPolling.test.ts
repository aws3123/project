import { renderHook, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTaskPolling } from './useTaskPolling'
import { useTaskStore } from '../store/taskStore'
import { useResultStore } from '../store/resultStore'
import { useLogStore } from '../store/logStore'
import { fetchTask } from '../api/task'
import type { TaskDetailResponse } from '../types/review'
import { fetchLogs } from '../api/logs'

vi.mock('../api/task', () => ({
  fetchTask: vi.fn(),
  toReviewResultFromDetail: vi.fn((detail: { result?: { riskScore?: number } }, taskId: string) => ({
    taskId,
    riskScore: detail?.result?.riskScore ?? 0,
    riskBreakdown: [],
    needHumanReview: false,
  })),
}))

vi.mock('../api/logs', () => ({
  fetchLogs: vi.fn(),
}))

const mockedFetchTask = vi.mocked(fetchTask)
const mockedFetchLogs = vi.mocked(fetchLogs)

describe('useTaskPolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    useTaskStore.getState().clear()
    useResultStore.getState().clear()
    useLogStore.getState().clear()

    useTaskStore.getState().upsertTasks([
      {
        taskId: 'task-1',
        projectId: 'p1',
        status: 'PENDING',
        createdAt: new Date().toISOString(),
      },
    ])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls immediately on start and stores terminal logs', async () => {
    mockedFetchTask.mockResolvedValue({
      task: {
        taskId: 'task-1',
        projectId: 'p1',
        status: 'SUCCESS',
        createdAt: new Date().toISOString(),
      },
      result: {
        riskScore: 0.2,
        needHumanReview: false,
      },
    } as TaskDetailResponse)
    mockedFetchLogs.mockResolvedValue([
      {
        node: 'diff',
        status: 'SUCCESS',
        durationMs: 10,
        inputSummary: 'in',
        outputSummary: 'out',
        timestamp: new Date().toISOString(),
      },
    ])

    renderHook(() => useTaskPolling('task-1', 'trace-1'))

    await act(async () => {
      await Promise.resolve()
    })

    expect(mockedFetchTask).toHaveBeenCalledTimes(1)
    expect(mockedFetchLogs).toHaveBeenCalledTimes(1)
    expect(useTaskStore.getState().tasks['task-1']?.status).toBe('SUCCESS')
    expect(useLogStore.getState().logs['task-1']?.length).toBe(1)
  })

  it('keeps polling active when fetchTask fails', async () => {
    mockedFetchTask.mockRejectedValue(new Error('network'))

    renderHook(() => useTaskPolling('task-1', 'trace-1'))

    await act(async () => {
      await Promise.resolve()
    })

    expect(mockedFetchTask).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
      await Promise.resolve()
    })

    expect(mockedFetchTask).toHaveBeenCalledTimes(2)
    expect(mockedFetchLogs).toHaveBeenCalledTimes(0)
  })
})
