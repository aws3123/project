import { renderHook, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBusinessRiskSse } from './useBusinessRiskSse'
import { fetchLogs } from '../api/logs'
import { useLogStore } from '../store/logStore'
import { useTaskStore } from '../store/taskStore'
import { useResultStore } from '../store/resultStore'

vi.mock('../api/logs', () => ({
  fetchLogs: vi.fn(),
}))

const mockedFetchLogs = vi.mocked(fetchLogs)
const storage = new Map<string, string>()

class MockEventSource {
  static instances: MockEventSource[] = []

  url: string
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null
  listeners = new Map<string, EventListener[]>()

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: EventListener) {
    const current = this.listeners.get(type) ?? []
    current.push(listener)
    this.listeners.set(type, current)
  }

  removeEventListener(type: string, listener: EventListener) {
    const current = this.listeners.get(type) ?? []
    this.listeners.set(type, current.filter((item) => item !== listener))
  }

  close() {}

  emit(type: string, data: string, lastEventId = '') {
    const event = { data, lastEventId } as MessageEvent
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event)
    }
  }
}

describe('useBusinessRiskSse', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    MockEventSource.instances = []
    storage.clear()
    useTaskStore.getState().clear()
    useResultStore.getState().clear()
    useLogStore.getState().clear()
    mockedFetchLogs.mockResolvedValue([])
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value)
        },
      },
    })
    vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('reconnects with lastEventId after disconnect', async () => {
    const { result } = renderHook(() => useBusinessRiskSse('task-1', 'session-1'))

    const first = MockEventSource.instances[0]
    expect(first.url).toContain('sessionId=session-1')
    expect(first.url).not.toContain('lastEventId=')

    await act(async () => {
      first.emit('task_processing', JSON.stringify({ taskId: 'task-1', status: 'PROCESSING' }), 'evt-1')
      first.onerror?.call(first as unknown as EventSource, new Event('error'))
      await vi.advanceTimersByTimeAsync(1500)
    })

    const second = MockEventSource.instances[1]
    expect(second.url).toContain('lastEventId=evt-1')
    expect(result.current.sseConnected).toBe(false)
  })

  it('updates status and result from terminal events and refreshes logs', async () => {
    mockedFetchLogs.mockResolvedValue([
      {
        node: 'verify_business_risks',
        status: 'SUCCESS',
        durationMs: 12,
        inputSummary: 'in',
        outputSummary: 'out',
        timestamp: new Date().toISOString(),
      },
    ])

    useTaskStore.getState().upsertTasks([
      {
        taskId: 'task-1',
        projectId: 'p1',
        status: 'PENDING',
        createdAt: new Date().toISOString(),
      },
    ])

    renderHook(() => useBusinessRiskSse('task-1', 'session-1'))
    const source = MockEventSource.instances[0]

    await act(async () => {
      source.onopen?.call(source as unknown as EventSource, new Event('open'))
      source.emit('task_completed', JSON.stringify({ taskId: 'task-1', status: 'SUCCESS', riskSummary: 'done' }), 'evt-2')
      await Promise.resolve()
    })

    expect(useTaskStore.getState().tasks['task-1']?.status).toBe('SUCCESS')
    expect(useResultStore.getState().results['task-1']?.riskSummary).toBe('done')
    expect(mockedFetchLogs).toHaveBeenCalledWith('task-1', undefined)
    expect(useLogStore.getState().logs['task-1']?.length).toBe(1)
  })

  it('does not downgrade a terminal task when an older processing event replays later', async () => {
    useTaskStore.getState().upsertTasks([
      {
        taskId: 'task-1',
        projectId: 'p1',
        status: 'SUCCESS',
        createdAt: new Date().toISOString(),
      },
    ])

    renderHook(() => useBusinessRiskSse('task-1', 'session-1'))
    const source = MockEventSource.instances[0]

    await act(async () => {
      source.onopen?.call(source as unknown as EventSource, new Event('open'))
      source.emit('task_processing', JSON.stringify({ taskId: 'task-1', status: 'PROCESSING' }), 'evt-old')
    })

    expect(useTaskStore.getState().tasks['task-1']?.status).toBe('SUCCESS')
  })
})
