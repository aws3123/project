import { useState } from 'react'
import type { ReviewTaskPayload, ResolvedSubmissionMode, SubmissionMode } from '../types/review'
import { useReviewSubmission } from '../hooks/useReviewSubmission'
import { useResultStore } from '../store/resultStore'
import { useTaskStore } from '../store/taskStore'
import { ReviewProgressPanel } from './ReviewProgressPanel'

interface ReviewSubmitFormProps {
  onSubmitted?: (options: { sourceMode: SubmissionMode; resolvedMode: ResolvedSubmissionMode; taskId: string }) => void
}

const defaultPayload: ReviewTaskPayload = {
  projectId: '',
  projectName: '',
  prLink: '',
  diffContent: '',
  question: '',
  mode: 'sync',
}

export function ReviewSubmitForm({ onSubmitted }: ReviewSubmitFormProps) {
  const [payload, setPayload] = useState(defaultPayload)
  const [mode, setMode] = useState<SubmissionMode>('sync')
  const [validationError, setValidationError] = useState<string | null>(null)
  const { submit, loading, error, steps } = useReviewSubmission()
  const upsertTasks = useTaskStore((state) => state.upsertTasks)
  const setResult = useResultStore((state) => state.setResult)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (mode === 'auto' && !payload.question.trim()) {
      setValidationError('自动判断模式下必须填写审查问题')
      return
    }
    if (!payload.projectId || !payload.projectName || !payload.prLink || !payload.diffContent) {
      setValidationError('请完整填写项目 ID、项目名称、PR 链接与 Diff 内容')
      return
    }
    setValidationError(null)

    try {
      const outcome = await submit(payload, mode)
      if (outcome.resolvedMode === 'sync') {
        setResult(outcome.result)
        onSubmitted?.({
          sourceMode: outcome.sourceMode,
          resolvedMode: 'sync',
          taskId: outcome.result.taskId,
        })
        return
      }

      upsertTasks([
        {
          taskId: outcome.taskId,
          projectId: payload.projectId,
          projectName: payload.projectName,
          prLink: payload.prLink,
          diffContent: payload.diffContent,
          mode,
          status: 'QUEUED',
          createdAt: new Date().toISOString(),
        },
      ])
      onSubmitted?.({
        sourceMode: outcome.sourceMode,
        resolvedMode: 'async',
        taskId: outcome.taskId,
      })
    } catch {
      // error state already set by useReviewSubmission hook
    }
  }

  function handleChange<T extends keyof ReviewTaskPayload>(key: T, value: ReviewTaskPayload[T]) {
    setPayload((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <form className="submit-form" onSubmit={handleSubmit}>
      <div className="submit-grid">
        <div className="field">
          <label htmlFor="projectId">项目 ID</label>
          <input
            id="projectId"
            value={payload.projectId}
            onChange={(e) => handleChange('projectId', e.target.value)}
            placeholder="project-alpha"
          />
        </div>
        <div className="field">
          <label htmlFor="projectName">项目名称</label>
          <input
            id="projectName"
            value={payload.projectName}
            onChange={(e) => handleChange('projectName', e.target.value)}
            placeholder="Project Alpha"
          />
        </div>
        <div className="field">
          <label htmlFor="prLink">PR 链接</label>
          <input
            id="prLink"
            value={payload.prLink}
            onChange={(e) => handleChange('prLink', e.target.value)}
            placeholder="https://git.example.com/..."
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor="diffContent">Diff 内容</label>
        <textarea
          id="diffContent"
          value={payload.diffContent}
          onChange={(e) => handleChange('diffContent', e.target.value)}
          rows={10}
          placeholder="@@ -1 +1 @@ ..."
        />
      </div>
      <div className="field">
        <label htmlFor="question">审查问题</label>
        <textarea
          id="question"
          value={payload.question}
          onChange={(e) => handleChange('question', e.target.value)}
          rows={4}
          placeholder="例如：帮我快速判断这个改动有没有明显上线风险"
        />
      </div>
      <div className="mode-toggle">
        <label>
          <input
            type="radio"
            name="mode"
            value="auto"
            checked={mode === 'auto'}
            onChange={() => setMode('auto')}
          />
          自动判断（根据问题内容和改动规模自动选择）
        </label>
        <label>
          <input
            type="radio"
            name="mode"
            value="sync"
            checked={mode === 'sync'}
            onChange={() => setMode('sync')}
          />
          同步审查（立即返回结果）
        </label>
        <label>
          <input
            type="radio"
            name="mode"
            value="async"
            checked={mode === 'async'}
            onChange={() => setMode('async')}
          />
          异步审查（返回 taskId 后轮询）
        </label>
      </div>
      <div className="submit-actions">
        <button type="submit" disabled={loading}>
          {loading ? '审查进行中…' : '提交审查'}
        </button>
      </div>
      <ReviewProgressPanel steps={steps} active={loading} />
      {validationError && <p className="error-text">{validationError}</p>}
      {error && <p className="error-text">{error}</p>}
    </form>
  )
}
