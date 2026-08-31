const TRACE_KEY = 'sentinel-trace-id'

export function getOrCreateTraceId() {
  const existing = sessionStorage.getItem(TRACE_KEY)
  if (existing) return existing
  const id = crypto.randomUUID()
  sessionStorage.setItem(TRACE_KEY, id)
  return id
}
