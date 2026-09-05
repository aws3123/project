import { http, HttpResponse } from 'msw'

export interface CapturedAsyncReviewRequest {
  projectId: string
  projectName: string
  prUrl: string
  diffContent: string
  mode: 'ASYNC' | 'SYNC'
  apiKeyHeader?: string | null
}

export interface CapturedDispatchReviewRequest {
  projectId: string
  projectName: string
  prUrl: string
  diffContent: string
  question: string
  apiKeyHeader?: string | null
}

export interface CapturedLogRequest {
  taskId: string
  traceId?: string | null
}

export interface CapturedFeedbackRequest {
  taskId: string
  feedbackType: string
}

export interface CapturedBusinessRiskSourceRequest {
  metadata: {
    schemaVersion: string
    projectId: string
    repo: string
    branch: string
    requestId?: string
    traceId?: string
    entryHint?: string
  }
  files: Array<{ name: string; size: number }>
  traceId?: string | null
}

let lastAsyncReviewRequest: CapturedAsyncReviewRequest | null = null
let lastDispatchReviewRequest: CapturedDispatchReviewRequest | null = null
let lastLogRequest: CapturedLogRequest | null = null
let lastBusinessRiskSourceRequest: CapturedBusinessRiskSourceRequest | null = null
let lastFeedbackRequest: CapturedFeedbackRequest | null = null

export function getLastAsyncReviewRequest() {
  return lastAsyncReviewRequest
}

export function getLastDispatchReviewRequest() {
  return lastDispatchReviewRequest
}

export function getLastLogRequest() {
  return lastLogRequest
}

export function getLastBusinessRiskSourceRequest() {
  return lastBusinessRiskSourceRequest
}

export function getLastFeedbackRequest() {
  return lastFeedbackRequest
}

export function resetCapturedRequests() {
  lastAsyncReviewRequest = null
  lastDispatchReviewRequest = null
  lastLogRequest = null
  lastBusinessRiskSourceRequest = null
  lastFeedbackRequest = null
}

export const handlers = [
  http.post('/api/review/async', async ({ request }) => {
    const body = (await request.json()) as Omit<CapturedAsyncReviewRequest, 'apiKeyHeader'>
    lastAsyncReviewRequest = {
      ...body,
      apiKeyHeader: request.headers.get('X-API-Key'),
    }

    return HttpResponse.json({ taskId: 'task_mock_1', status: 'QUEUED' })
  }),

  http.post('/api/review/sync', async () => {
    return HttpResponse.json({
      taskId: 'task_sync_1',
      riskScore: 0.27,
      riskSummary: 'mock summary',
      needHumanReview: false,
      details: ['mock detail'],
    })
  }),

  http.post('/api/review/dispatch', async ({ request }) => {
    const body = (await request.json()) as Omit<CapturedDispatchReviewRequest, 'apiKeyHeader'>
    lastDispatchReviewRequest = {
      ...body,
      apiKeyHeader: request.headers.get('X-API-Key'),
    }

    if (body.question.includes('快速')) {
      return HttpResponse.json({
        route: 'SYNC',
        taskId: 'task_dispatch_sync',
        status: 'SUCCESS',
        dispatchReason: 'direct_sync_small_simple',
        confidence: 1,
        usedLightweightClassifier: false,
        result: {
          taskId: 'task_dispatch_sync',
          riskScore: 0.11,
          riskSummary: 'dispatch sync summary',
          needHumanReview: false,
          details: ['dispatch sync detail'],
        },
      })
    }

    return HttpResponse.json({
      route: 'ASYNC',
      taskId: 'task_dispatch_async',
      status: 'QUEUED',
      dispatchReason: 'direct_async_large_risky',
      confidence: 1,
      usedLightweightClassifier: false,
    })
  }),

  http.post('/api/business-risk/source', async ({ request }) => {
    const formData = await request.formData()
    const metadataEntry = formData.get('metadata')
    const metadataText = typeof metadataEntry === 'string'
      ? metadataEntry
      : metadataEntry
        ? await metadataEntry.text()
        : '{}'
    const metadata = JSON.parse(metadataText) as CapturedBusinessRiskSourceRequest['metadata']
    const files = formData.getAll('files').map((entry) => {
      const file = entry as File
      return { name: file.name, size: file.size }
    })

    lastBusinessRiskSourceRequest = {
      metadata,
      files,
      traceId: request.headers.get('X-Trace-Id'),
    }

    return HttpResponse.json(
      {
        taskId: 'biz-risk-1',
        status: 'PENDING',
        sessionId: 'session-biz-risk-1',
        traceId: 'trace-biz-risk-1',
        streamUrl: '/api/business-risk/stream',
      },
      { status: 202 },
    )
  }),

  http.get('/api/review/tasks/:taskId', async ({ params }) => {
    return HttpResponse.json({
      task: {
        taskId: String(params.taskId),
        projectId: 'project-x',
        projectName: 'Project X',
        status: 'SUCCESS',
        mode: 'ASYNC',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
      result: {
        riskScore: 0.2,
        riskSummary: 'task detail mock',
        needHumanReview: false,
      },
    })
  }),

  http.get('/api/review/logs/:taskId', async ({ params, request }) => {
    lastLogRequest = {
      taskId: String(params.taskId),
      traceId: request.headers.get('X-Trace-Id'),
    }

    return HttpResponse.json([
      {
        node: 'diff',
        status: 'SUCCESS',
        durationMs: 12,
        input: 'input mock',
        output: 'output mock',
        timestamp: '2026-04-18T00:00:00.000Z',
      },
    ])
  }),

  http.post('/api/review/handoff/:taskId', async ({ params, request }) => {
    const payload = (await request.json()) as { decision: string; operator?: string; comment?: string }

    return HttpResponse.json({
      task: {
        taskId: String(params.taskId),
        projectId: 'project-x',
        projectName: 'Project X',
        status: payload.decision === 'APPROVED' ? 'SUCCESS' : 'FAILED',
        mode: 'ASYNC',
        handoffDecision: payload.decision,
        handoffOperator: payload.operator,
        handoffComment: payload.comment,
        handoffHandledAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
      result: {
        riskScore: 0.2,
        riskSummary: 'handoff mock',
        needHumanReview: false,
      },
    })
  }),

  http.post('/api/feedback/submit', async ({ request }) => {
    const body = await request.json() as { taskId: string; feedbackType: string }
    lastFeedbackRequest = { taskId: body.taskId, feedbackType: body.feedbackType }

    return HttpResponse.json(
      { id: 1, status: 'accepted' },
      { status: 201 },
    )
  }),

  http.get('/api/feedback/stats', ({ request }) => {
    const url = new URL(request.url)
    const source = url.searchParams.get('source')

    if (source === 'business_risk') {
      return HttpResponse.json({
        total: 4,
        thumbs_up: 1,
        thumbs_down: 3,
        ratio: '0.25',
        daily_breakdown: [
          { date: '2026-09-04', thumbs_up: 1, thumbs_down: 2 },
          { date: '2026-09-05', thumbs_up: 0, thumbs_down: 1 },
        ],
      })
    }

    return HttpResponse.json({
      total: 8,
      thumbs_up: 6,
      thumbs_down: 2,
      ratio: '0.75',
      daily_breakdown: [
        { date: '2026-09-04', thumbs_up: 3, thumbs_down: 1 },
        { date: '2026-09-05', thumbs_up: 3, thumbs_down: 1 },
      ],
    })
  }),

  http.get('/api/feedback/export', ({ request }) => {
    const url = new URL(request.url)
    const source = url.searchParams.get('source')
    const page = Number(url.searchParams.get('page') ?? '1')
    const filterSource = source ?? undefined

    const allRecords = [
      {
        id: 1,
        taskId: 'task-down-1',
        sessionId: 'session-1',
        feedbackType: 'thumbs_down',
        category: '误报',
        comment: '这条不是风险，标错了',
        metadata: null,
        userAgent: null,
        source: 'review',
        traceId: 'trace-111',
        createdAt: '2026-09-04T10:00:00Z',
      },
      {
        id: 2,
        taskId: 'task-up-1',
        sessionId: 'session-2',
        feedbackType: 'thumbs_up',
        category: '结果准确',
        comment: null,
        metadata: null,
        userAgent: null,
        source: 'review',
        traceId: 'trace-222',
        createdAt: '2026-09-05T09:00:00Z',
      },
      {
        id: 3,
        taskId: 'task-biz-down',
        sessionId: 'session-3',
        feedbackType: 'thumbs_down',
        category: '遗漏风险',
        comment: '漏了一个空指针',
        metadata: null,
        userAgent: null,
        source: 'business_risk',
        traceId: 'trace-333',
        createdAt: '2026-09-05T11:00:00Z',
      },
    ].filter((r) => !filterSource || r.source === filterSource)

    const size = Number(url.searchParams.get('size') ?? '10')
    const start = (page - 1) * size
    const records = allRecords.slice(start, start + size)

    return HttpResponse.json({
      records,
      total: allRecords.length,
      size,
      current: page,
      pages: Math.max(1, Math.ceil(allRecords.length / size)),
    })
  }),
]
