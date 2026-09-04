/**
 * SSE 流式解析器 —— fetch + ReadableStream 方案
 *
 * 为什么不用原生 EventSource：
 * 1. EventSource 只支持 GET，无法 POST 审查请求体（diff 内容远超 URL 长度限制）
 * 2. EventSource 无法携带自定义鉴权头
 *
 * 核心难点：SSE 帧以 \n\n 分隔，而网络 chunk 的边界与帧边界完全不对齐
 * （一帧可能拆在多个 chunk 里、一个 chunk 可能含多帧），必须用缓冲区重组。
 */

export interface SseEvent {
  event: string
  data: string
  id?: string
}

export class StreamIdleTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`流式响应空闲超时（${timeoutMs}ms 内未收到任何数据）`)
    this.name = 'StreamIdleTimeoutError'
  }
}

export interface ConsumeSseStreamOptions {
  /** 空闲超时：连续无数据 chunk 的最大间隔（服务端每 15s 发心跳，默认 30s） */
  idleTimeoutMs?: number
  /** 空闲超时触发时的清理回调（调用方应 abort 底层 fetch） */
  onIdleTimeout?: () => void
}

/**
 * 消费一个 SSE 响应流，逐帧回调。
 *
 * @param response 已 fetch 的 Response（body 为 ReadableStream）
 * @param onEvent 每个完整 SSE 帧的回调；回调内抛出的异常会向上传播并终止消费
 */
export async function consumeSseStream(
  response: Response,
  onEvent: (event: SseEvent) => void,
  options: ConsumeSseStreamOptions = {},
): Promise<void> {
  const idleTimeoutMs = options.idleTimeoutMs ?? 30_000
  if (!response.body) {
    throw new Error('响应不包含可读流')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await readWithIdleTimeout(reader, idleTimeoutMs)
      if (done) {
        break
      }
      buffer += decoder.decode(value, { stream: true })

      // 按帧分隔符切分；最后一段可能是不完整帧，留在缓冲区等下个 chunk
      // 同时兼容 \r\n\r\n 分隔（某些代理会改写换行符）
      let frameEnd = findFrameBoundary(buffer)
      while (frameEnd !== -1) {
        const frame = buffer.slice(0, frameEnd.index)
        buffer = buffer.slice(frameEnd.end)
        const event = parseFrame(frame)
        if (event) {
          onEvent(event)
        }
        frameEnd = findFrameBoundary(buffer)
      }
    }
    // 流结束：处理缓冲区中最后一帧（服务端正常结束时应该已包含结尾分隔符，此处兜底）
    const trailing = parseFrame(buffer)
    if (trailing) {
      onEvent(trailing)
    }
  } catch (error) {
    if (error instanceof StreamIdleTimeoutError) {
      options.onIdleTimeout?.()
      reader.cancel().catch(() => undefined)
    }
    throw error
  } finally {
    reader.releaseLock()
  }
}

function findFrameBoundary(buffer: string): { index: number; end: number } | -1 {
  const lf = buffer.indexOf('\n\n')
  const crlf = buffer.indexOf('\r\n\r\n')
  if (lf === -1 && crlf === -1) return -1
  if (crlf === -1 || (lf !== -1 && lf < crlf)) {
    return { index: lf, end: lf + 2 }
  }
  return { index: crlf, end: crlf + 4 }
}

/** 解析单帧：event:/data:/id: 行；注释行（:开头）与空行忽略。 */
function parseFrame(frame: string): SseEvent | null {
  let eventName = 'message'
  let id: string | undefined
  const dataLines: string[] = []

  for (const rawLine of frame.split('\n')) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    if (!line || line.startsWith(':')) {
      continue
    }
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // SSE 规范：冒号后仅允许一个空格作为分隔
      const value = line.slice(5)
      dataLines.push(value.startsWith(' ') ? value.slice(1) : value)
    } else if (line.startsWith('id:')) {
      id = line.slice(3).trim()
    }
  }

  if (dataLines.length === 0) {
    return null
  }
  return { event: eventName, data: dataLines.join('\n'), id }
}

async function readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  timeoutMs: number,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeoutPromise = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new StreamIdleTimeoutError(timeoutMs)), timeoutMs)
  })
  try {
    return await Promise.race([reader.read(), timeoutPromise])
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer)
    }
  }
}
