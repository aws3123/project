import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { submitBusinessRiskSourceForm } from '../api/businessRisk'
import { useTaskStore } from '../store/taskStore'
import { getOrCreateTraceId } from '../utils/trace'
import type { BusinessRiskSourceSubmitMetadata } from '../types/businessRisk'

const MAX_JAVA_FILES = 50

function isJavaFile(file: File) {
  return file.name.toLowerCase().endsWith('.java')
}

function normalizeInitialStatus(status?: string) {
  if (status === 'QUEUED') return 'QUEUED'
  if (status === 'PENDING') return 'PENDING'
  if (status === 'PROCESSING') return 'PROCESSING'
  if (status === 'SUCCESS') return 'SUCCESS'
  if (status === 'FAILED') return 'FAILED'
  if (status === 'NEED_REVIEW') return 'NEED_REVIEW'
  if (status === 'HUMAN_REVIEW') return 'HUMAN_REVIEW'
  return 'PENDING'
}

export function BusinessRiskSourcePage() {
  const navigate = useNavigate()
  const upsertTasks = useTaskStore((state) => state.upsertTasks)
  const defaultTraceId = getOrCreateTraceId()

  const [projectId, setProjectId] = useState('ticket-demo')
  const [repo, setRepo] = useState('ticket-service')
  const [branch, setBranch] = useState('main')
  const [requestId, setRequestId] = useState('')
  const [traceId, setTraceId] = useState(defaultTraceId)
  const [entryHint, setEntryHint] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successInfo, setSuccessInfo] = useState<{ taskId: string; sessionId: string; traceId: string } | null>(null)

  const fileNames = useMemo(() => files.map((file) => file.name), [files])

  function withTrace(message: string, submitError?: ApiError) {
    return submitError?.traceId ? `${message}（traceId: ${submitError.traceId}）` : message
  }

  function validateForm() {
    if (!projectId || !repo || !branch) {
      return 'projectId / repo / branch 为必填项'
    }
    if (files.length === 0) {
      return '请至少上传 1 个 .java 文件'
    }
    if (files.length > MAX_JAVA_FILES) {
      return '最多上传 50 个 .java 文件'
    }
    if (files.some((file) => !isJavaFile(file))) {
      return '仅支持上传 .java 文件'
    }
    return null
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const nextFiles = Array.from(event.target.files ?? [])
    setFiles(nextFiles)
    setSuccessInfo(null)

    if (nextFiles.length > MAX_JAVA_FILES) {
      setError('最多上传 50 个 .java 文件')
      return
    }
    if (nextFiles.some((file) => !isJavaFile(file))) {
      setError('仅支持上传 .java 文件')
      return
    }
    setError(null)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setSuccessInfo(null)

    const validationError = validateForm()
    if (validationError) {
      setError(validationError)
      return
    }

    setError(null)

    const metadata: BusinessRiskSourceSubmitMetadata = {
      schemaVersion: '2.0',
      projectId,
      repo,
      branch,
      requestId: requestId || undefined,
      traceId: traceId || undefined,
      entryHint: entryHint || undefined,
    }

    try {
      setSubmitting(true)
      const response = await submitBusinessRiskSourceForm({ metadata, files }, traceId || undefined)
      const effectiveTraceId = response.traceId || traceId || defaultTraceId
      setSuccessInfo({
        taskId: response.taskId,
        sessionId: response.sessionId,
        traceId: effectiveTraceId,
      })
      upsertTasks([
        {
          taskId: response.taskId,
          projectId,
          projectName: repo,
          status: normalizeInitialStatus(response.status),
          mode: 'business_risk_source',
          sessionId: response.sessionId,
          traceId: effectiveTraceId,
          createdAt: new Date().toISOString(),
        },
      ])
      navigate(`/business-risk/${response.taskId}`)
    } catch (submitError) {
      if (submitError instanceof ApiError) {
        if (submitError.status === 422) {
          setError(withTrace(submitError.message || '后端校验失败，请检查 metadata 和文件内容', submitError))
        } else if (submitError.status === 413) {
          setError(withTrace('上传体积过大，请减少文件数量或缩小文件体积', submitError))
        } else if ([500, 502, 503].includes(submitError.status)) {
          setError(withTrace('服务暂时不可用，请稍后重试', submitError))
        } else {
          setError(withTrace(submitError.message || '提交失败', submitError))
        }
      } else {
        setError(submitError instanceof Error ? submitError.message : '提交失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="page-shell">
      <div className="panel">
        <h2 className="page-title">业务风险源码上传</h2>
        <p className="page-desc">上传 1 到 50 个 .java 文件，后端将自动构造源码包并异步执行业务风险分析。</p>
      </div>

      <div className="panel">
        <form className="submit-form" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="projectId">项目 ID</label>
            <input id="projectId" value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="例如：ticket-demo" />
          </div>

          <div className="field">
            <label htmlFor="repo">仓库名</label>
            <input id="repo" value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="例如：ticket-service" />
          </div>

          <div className="field">
            <label htmlFor="branch">分支</label>
            <input id="branch" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="例如：main" />
          </div>

          <div className="field">
            <label htmlFor="requestId">请求 ID（可选）</label>
            <input id="requestId" value={requestId} onChange={(e) => setRequestId(e.target.value)} placeholder="可选" />
          </div>

          <div className="field">
            <label htmlFor="traceId">Trace ID（可选）</label>
            <input id="traceId" value={traceId} onChange={(e) => setTraceId(e.target.value)} placeholder="可选" />
          </div>

          <div className="field">
            <label htmlFor="entryHint">入口提示（可选）</label>
            <input id="entryHint" value={entryHint} onChange={(e) => setEntryHint(e.target.value)} placeholder="例如：TicketService#reserve" />
          </div>

          <div className="field">
            <label htmlFor="businessRiskFiles">上传 .java 文件</label>
            <input id="businessRiskFiles" type="file" multiple accept=".java" onChange={handleFileChange} />
            <p className="page-desc">已选择 {files.length} 个文件</p>
            {fileNames.length > 0 && (
              <ul>
                {fileNames.map((fileName) => (
                  <li key={fileName}>{fileName}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="submit-actions">
            <button type="submit" disabled={submitting}>
              {submitting ? '提交中…' : '提交业务风险审查'}
            </button>
          </div>

          {successInfo && (
            <div className="page-desc">
              <p>任务已创建：{successInfo.taskId}</p>
              <p>Session ID：{successInfo.sessionId}</p>
              <p>Trace ID：{successInfo.traceId}</p>
            </div>
          )}

          {error && <p className="error-text">{error}</p>}
        </form>
      </div>
    </section>
  )
}
