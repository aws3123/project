export interface ApiErrorPayload {
  status: number
  message: string
  traceId?: string
  details?: unknown
}

export class ApiError extends Error {
  status: number
  traceId?: string
  details?: unknown

  constructor(payload: ApiErrorPayload) {
    super(payload.message)
    this.status = payload.status
    this.traceId = payload.traceId
    this.details = payload.details
  }
}

export interface RequestOptions extends RequestInit {
  traceId?: string
}

const defaultJsonHeaders: HeadersInit = {
  'Content-Type': 'application/json',
}

function getBaseUrl() {
  return import.meta.env.VITE_API_BASE_URL ?? ''
}

function getApiKeyHeaders(): HeadersInit {
  const apiKey = import.meta.env.VITE_API_KEY
  if (!apiKey) {
    return {}
  }
  const headerName = import.meta.env.VITE_API_KEY_HEADER ?? 'X-API-Key'
  return { [headerName]: apiKey }
}

export async function http<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = Number(import.meta.env.VITE_HTTP_TIMEOUT_MS ?? 120000)
  const id = window.setTimeout(() => controller.abort(), timeout)
  const isFormDataBody = options.body instanceof FormData

  try {
    const response = await fetch(`${getBaseUrl()}${path}`, {
      ...options,
      headers: {
        ...(isFormDataBody ? {} : defaultJsonHeaders),
        ...getApiKeyHeaders(),
        ...(options.headers ?? {}),
        'X-Trace-Id': options.traceId ?? crypto.randomUUID(),
      },
      signal: controller.signal,
    })

    const contentType = response.headers.get('content-type') ?? ''
    const isJson = contentType.includes('application/json')
    const body = isJson ? await response.json() : await response.text()

    if (!response.ok) {
      throw new ApiError({
        status: response.status,
        message: isJson ? body?.message ?? 'API 调用失败' : 'API 调用失败',
        traceId: response.headers.get('x-trace-id') ?? options.traceId,
        details: body,
      })
    }

    return body as T
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }

    throw new ApiError({ status: 0, message: '网络异常或请求超时', details: error })
  } finally {
    clearTimeout(id)
  }
}

/**
 * Download a URL and return the raw Blob (for file downloads that need auth headers).
 */
export async function httpBlob(url: string, options: RequestOptions = {}): Promise<Blob> {
  const controller = new AbortController()
  const timeout = Number(import.meta.env.VITE_HTTP_TIMEOUT_MS ?? 120000)
  const id = window.setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(`${getBaseUrl()}${url}`, {
      ...options,
      headers: {
        ...getApiKeyHeaders(),
        ...(options.headers ?? {}),
        'X-Trace-Id': options.traceId ?? crypto.randomUUID(),
      },
      signal: controller.signal,
    })

    if (!response.ok) {
      throw new ApiError({
        status: response.status,
        message: '下载失败',
        traceId: response.headers.get('x-trace-id') ?? options.traceId,
      })
    }

    return await response.blob()
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError({ status: 0, message: '网络异常或请求超时', details: error })
  } finally {
    clearTimeout(id)
  }
}
