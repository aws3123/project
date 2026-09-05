import type {
  BackendReviewAsyncResponse,
  BackendReviewDispatchRequest,
  BackendReviewDispatchResponse,
  BackendReviewSyncRequest,
  BackendReviewSyncResponse,
  ReviewResult,
  ReviewStreamProgressEvent,
  ReviewTaskPayload,
  SubmissionOutcome,
} from '../types/review'
import { ApiError, getApiKeyHeaders, getBaseUrl, http } from './client'
import { consumeSseStream } from './stream'

const SYNC_ENDPOINT = '/api/review/sync'
const SYNC_STREAM_ENDPOINT = '/api/review/sync/stream'
const ASYNC_ENDPOINT = '/api/review/async'
const DISPATCH_ENDPOINT = '/api/review/dispatch'

function toBackendMode(mode: ReviewTaskPayload['mode']): BackendReviewSyncRequest['mode'] {
  return mode === 'sync' ? 'SYNC' : 'ASYNC'
}

function toBackendPayload(payload: ReviewTaskPayload): BackendReviewSyncRequest {
  return {
    projectId: payload.projectId,
    projectName: payload.projectName,
    prUrl: payload.prLink,
    diffContent: payload.diffContent,
    mode: toBackendMode(payload.mode),
  }
}

function toReviewResult(payload: BackendReviewSyncResponse): ReviewResult {
  return {
    taskId: payload.taskId,
    riskScore: payload.riskScore,
    riskBreakdown: [],
    needHumanReview: payload.needHumanReview,
    riskSummary: payload.riskSummary,
    details: payload.details,
  }
}

function toDispatchPayload(payload: ReviewTaskPayload): BackendReviewDispatchRequest {
  return {
    projectId: payload.projectId,
    projectName: payload.projectName,
    prUrl: payload.prLink,
    diffContent: payload.diffContent,
    question: payload.question,
  }
}

export function toSubmissionOutcomeFromDispatch(response: BackendReviewDispatchResponse): SubmissionOutcome {
  if (response.route === 'SYNC' && response.result) {
    return {
      sourceMode: 'auto',
      resolvedMode: 'sync',
      result: toReviewResult(response.result),
    }
  }

  return {
    sourceMode: 'auto',
    resolvedMode: 'async',
    taskId: response.taskId,
  }
}

export async function submitSync(payload: ReviewTaskPayload, traceId?: string) {
  const response = await http<BackendReviewSyncResponse>(SYNC_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(toBackendPayload(payload)),
    traceId,
  })
  return toReviewResult(response)
}

/**
 * 流式同步审查：POST 发起，SSE 逐事件接收审查进度。
 *
 * 与 submitSync 的区别：
 * - 不再一次性等待完整结果（旧模式前端 120s 干等）
 * - 进度事件实时回调 onProgress，供进度时间线 UI 渲染
 * - 心跳由服务端每 15s 推送，空闲超时（默认 30s）才会中断——
 *   长任务不会再被总时长一刀切
 *
 * 终态：run_finished 返回完整结果（契约与旧同步响应一致）；
 * run_error / 流中断 / 空闲超时抛 ApiError。
 */
export async function submitSyncStream(
  payload: ReviewTaskPayload,
  onProgress: (progress: ReviewStreamProgressEvent) => void,
  traceId?: string,
): Promise<ReviewResult> {
  const controller = new AbortController()
  const idleTimeoutMs = Number(import.meta.env.VITE_STREAM_IDLE_TIMEOUT_MS ?? 30000)

  const response = await fetch(`${getBaseUrl()}${SYNC_STREAM_ENDPOINT}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getApiKeyHeaders(),
      'X-Trace-Id': traceId ?? crypto.randomUUID(),
    },
    body: JSON.stringify(toBackendPayload(payload)),
    signal: controller.signal,
  })

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? ''
    const body = contentType.includes('application/json')
      ? await response.json()
      : await response.text()
    throw new ApiError({
      status: response.status,
      message: '流式审查请求失败',
      traceId: response.headers.get('x-trace-id') ?? traceId,
      details: body,
    })
  }

  let result: ReviewResult | null = null

  await consumeSseStream(
    response,
    (event) => {
      if (event.event === 'run_finished') {
        const terminal = JSON.parse(event.data) as {
          taskId: string
          result: BackendReviewSyncResponse
        }
        result = toReviewResult(terminal.result)
        return
      }
      if (event.event === 'run_error') {
        const error = JSON.parse(event.data) as {
          taskId: string
          errorCode?: string
          errorMessage?: string
        }
        throw new ApiError({
          status: 200,
          message: error.errorMessage ?? '审查执行失败',
          traceId,
          details: error,
        })
      }
      if (event.event === 'heartbeat') {
        return // 心跳仅用于保活/空闲检测，不进进度回调
      }
      try {
        onProgress(JSON.parse(event.data) as ReviewStreamProgressEvent)
      } catch {
        // 非法进度载荷不中断整条流
      }
    },
    { idleTimeoutMs, onIdleTimeout: () => controller.abort() },
  )

  if (!result) {
    throw new ApiError({
      status: 0,
      message: '流式响应结束但未收到审查结果',
      traceId,
    })
  }
  return result
}

export function submitAsync(payload: ReviewTaskPayload, traceId?: string) {
  return http<BackendReviewAsyncResponse>(ASYNC_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(toBackendPayload(payload)),
    traceId,
  })
}

export function submitDispatch(payload: ReviewTaskPayload, traceId?: string) {
  return http<BackendReviewDispatchResponse>(DISPATCH_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(toDispatchPayload(payload)),
    traceId,
  })
}
