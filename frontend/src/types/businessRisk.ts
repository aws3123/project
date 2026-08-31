export interface BusinessRiskSourceSubmitMetadata {
  schemaVersion: string
  projectId: string
  repo: string
  branch: string
  requestId?: string
  traceId?: string
  entryHint?: string
}

export interface BusinessRiskSourceUploadInput {
  metadata: BusinessRiskSourceSubmitMetadata
  files: File[]
}

export interface BusinessRiskSourceSubmitResponse {
  taskId: string
  status: string
  sessionId: string
  traceId: string
}
