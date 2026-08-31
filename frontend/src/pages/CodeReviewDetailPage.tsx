import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchLogs } from '../api/logs'
import { fetchTask, submitHandoff, toReviewResultFromDetail, toReviewTaskFromDetail } from '../api/task'
import { FeedbackWidget } from '../components/FeedbackWidget'
import { LogsPanel } from '../components/LogsPanel'
import { ReviewResultCard } from '../components/ReviewResultCard'
import { TaskStatusBadge } from '../components/TaskStatusBadge'
import { TaskStatusTimeline } from '../components/TaskStatusTimeline'
import { TaskSummarySidebar } from '../components/TaskSummarySidebar'
import { useTaskPolling } from '../hooks/useTaskPolling'
import { selectLogs, useLogStore } from '../store/logStore'
import { selectResult, useResultStore } from '../store/resultStore'
import type { ReviewTaskStatus } from '../store/status'
import { selectTask, useTaskStore } from '../store/taskStore'
import type { HandoffDecision } from '../types/review'
import { getOrCreateTraceId } from '../utils/trace'

export function CodeReviewDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const traceId = getOrCreateTraceId()

  const task = useTaskStore((state) => (taskId ? selectTask(taskId)(state) : undefined))
  const result = useResultStore((state) => (taskId ? selectResult(taskId)(state) : undefined))
  const logs = useLogStore((state) => (taskId ? selectLogs(taskId)(state) : []))
  const upsertTasks = useTaskStore((state) => state.upsertTasks)
  const setResult = useResultStore((state) => state.setResult)
  const setLogs = useLogStore((state) => state.setLogs)

  const [decision, setDecision] = useState<HandoffDecision>('APPROVED')
  const [operator, setOperator] = useState('')
  const [comment, setComment] = useState('')
  const [submittingHandoff, setSubmittingHandoff] = useState(false)
  const [handoffError, setHandoffError] = useState<string | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)

  // Redirect if this is actually a business risk task
  useEffect(() => {
    if (task?.mode === 'business_risk_source') {
      navigate(`/business-risk/${taskId}`, { replace: true })
    }
  }, [task?.mode, taskId, navigate])

  // Always poll for code review tasks (no SSE)
  const effectiveTraceId = task?.traceId || traceId
  useTaskPolling(taskId ?? null, effectiveTraceId, true)

  // Initial fetch
  useEffect(() => {
    if (!taskId) return
    fetchTask(taskId, traceId)
      .then((detail) => {
        const mappedTask = toReviewTaskFromDetail(detail, taskId, task)
        if (mappedTask.mode === 'business_risk_source') {
          navigate(`/business-risk/${taskId}`, { replace: true })
          return
        }
        upsertTasks([mappedTask])
        const mappedResult = toReviewResultFromDetail(detail, taskId)
        if (mappedResult) {
          setResult(mappedResult)
        }
      })
      .catch((err) => {
        setFetchError(err.message ?? '加载任务失败')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId])

  // Fetch logs
  useEffect(() => {
    if (!taskId) return
    fetchLogs(taskId, traceId)
      .then((entries) => setLogs(taskId, entries))
      .catch(() => setLogs(taskId, []))
  }, [taskId, traceId, setLogs])

  const isHumanReview = task?.status === 'HUMAN_REVIEW' || (task?.status as ReviewTaskStatus) === 'NEED_REVIEW'

  async function handleHandoffSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!taskId || !task) return

    try {
      setSubmittingHandoff(true)
      setHandoffError(null)
      const response = await submitHandoff(
        taskId,
        { decision, operator: operator || undefined, comment: comment || undefined },
        traceId,
      )
      const mappedTask = toReviewTaskFromDetail(response, taskId, task)
      upsertTasks([mappedTask])
      const mappedResult = toReviewResultFromDetail(response, taskId)
      if (mappedResult) setResult(mappedResult)
      setComment('')
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : '提交人工复核失败')
    } finally {
      setSubmittingHandoff(false)
    }
  }

  if (!taskId) {
    return <p className="error-text">缺少 taskId</p>
  }

  const effectiveSessionId = task?.sessionId || `session-${taskId}`

  return (
    <section className="page-shell task-detail-page">
      <div className="panel result-page-header">
        <div>
          <h2 className="page-title">代码审查 · 任务详情</h2>
          <p className="page-desc">Task ID: {taskId}</p>
        </div>
        {task && <TaskStatusBadge status={task.status} />}
      </div>

      {fetchError ? (
        <div className="panel">
          <div className="empty-state">加载失败：{fetchError}</div>
        </div>
      ) : task ? (
        <div className="task-detail-layout">
          <div className="task-detail-main">
            <TaskStatusTimeline
              status={task.status}
              failedMessage="任务执行失败，请检查错误信息或重新触发任务。"
            />

            {result ? (
              <>
                <div className="panel">
                  <ReviewResultCard result={result} />
                </div>
                <div className="panel">
                  <FeedbackWidget
                    taskId={taskId}
                    sessionId={effectiveSessionId}
                    source="review"
                    systemAnswer={JSON.stringify({
                      riskSummary: result.riskSummary,
                      details: result.details,
                    })}
                  />
                </div>
              </>
            ) : (
              <div className="panel">
                <div className="empty-state">暂无审查结果，请等待任务完成。</div>
              </div>
            )}

            {isHumanReview && (
              <div className="panel handoff-panel">
                <h3>人工复核决策</h3>
                <p className="page-desc">当前任务已进入人工复核环节，请提交最终决策。</p>
                <form className="handoff-form" onSubmit={handleHandoffSubmit}>
                  <div className="field">
                    <label htmlFor="decision">决策</label>
                    <select id="decision" value={decision} onChange={(e) => setDecision(e.target.value as HandoffDecision)}>
                      <option value="APPROVED">APPROVED（通过）</option>
                      <option value="REJECTED">REJECTED（拒绝）</option>
                      <option value="CHANGES_REQUESTED">CHANGES_REQUESTED（要求修改）</option>
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="operator">处理人</label>
                    <input id="operator" value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="例如：alice" />
                  </div>
                  <div className="field">
                    <label htmlFor="comment">备注</label>
                    <textarea id="comment" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="补充复核说明（可选）" rows={4} />
                  </div>
                  <div className="submit-actions">
                    <button type="submit" disabled={submittingHandoff}>
                      {submittingHandoff ? '提交中…' : '提交复核决策'}
                    </button>
                  </div>
                </form>
                {handoffError && <p className="error-text">{handoffError}</p>}
              </div>
            )}

            <div className="panel">
              <LogsPanel logs={logs} />
            </div>
          </div>

          <TaskSummarySidebar
            taskId={taskId}
            task={task}
            effectiveSessionId={effectiveSessionId}
            effectiveTraceId={effectiveTraceId}
          />
        </div>
      ) : (
        <div className="panel">
          <div className="empty-state">正在加载任务信息…</div>
        </div>
      )}
    </section>
  )
}
