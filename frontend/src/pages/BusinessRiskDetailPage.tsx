import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchLogs } from '../api/logs'
import { fetchTask, toReviewResultFromDetail, toReviewTaskFromDetail } from '../api/task'
import { FeedbackWidget } from '../components/FeedbackWidget'
import { LogsPanel } from '../components/LogsPanel'
import { ReviewResultCard } from '../components/ReviewResultCard'
import { TaskStatusBadge } from '../components/TaskStatusBadge'
import { TaskStatusTimeline } from '../components/TaskStatusTimeline'
import { TaskSummarySidebar } from '../components/TaskSummarySidebar'
import { useTaskPolling } from '../hooks/useTaskPolling'
import { useBusinessRiskSse } from '../hooks/useBusinessRiskSse'
import { selectLogs, useLogStore } from '../store/logStore'
import { selectResult, useResultStore } from '../store/resultStore'
import { selectTask, useTaskStore } from '../store/taskStore'
import { getOrCreateTraceId } from '../utils/trace'

export function BusinessRiskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const traceId = getOrCreateTraceId()

  const task = useTaskStore((state) => (taskId ? selectTask(taskId)(state) : undefined))
  const result = useResultStore((state) => (taskId ? selectResult(taskId)(state) : undefined))
  const logs = useLogStore((state) => (taskId ? selectLogs(taskId)(state) : []))
  const upsertTasks = useTaskStore((state) => state.upsertTasks)
  const setResult = useResultStore((state) => state.setResult)
  const setLogs = useLogStore((state) => state.setLogs)

  const [fetchError, setFetchError] = useState<string | null>(null)

  const effectiveSessionId = taskId ? task?.sessionId || `session-${taskId}` : ''
  const { sseConnected } = useBusinessRiskSse(taskId ?? null, effectiveSessionId)
  const effectiveTraceId = task?.traceId || traceId

  // Poll only when SSE is not connected (fallback)
  useTaskPolling(taskId ?? null, effectiveTraceId, !sseConnected)

  // Redirect if this is not a business risk task
  useEffect(() => {
    if (task && task.mode !== 'business_risk_source') {
      navigate(`/code-review/${taskId}`, { replace: true })
    }
  }, [task, taskId, navigate])

  // Initial fetch
  useEffect(() => {
    if (!taskId) return
    fetchTask(taskId, traceId)
      .then((detail) => {
        const mappedTask = toReviewTaskFromDetail(detail, taskId, task)
        if (mappedTask.mode !== 'business_risk_source') {
          navigate(`/code-review/${taskId}`, { replace: true })
          return
        }
        upsertTasks([mappedTask])
        const mappedResult = toReviewResultFromDetail(detail, taskId)
        if (mappedResult) setResult(mappedResult)
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

  if (!taskId) {
    return <p className="error-text">缺少 taskId</p>
  }

  const sseStateText = `事件流连接：${sseConnected ? '已连接' : '已断开（轮询兜底中）'}`

  return (
    <section className="page-shell task-detail-page">
      <div className="panel result-page-header">
        <div>
          <h2 className="page-title">业务风险 · 任务详情</h2>
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
              sseStateText={sseStateText}
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
                    source="business_risk"
                    systemAnswer={JSON.stringify({
                      riskSummary: result.riskSummary,
                      details: result.details,
                    })}
                  />
                </div>
              </>
            ) : (
              <div className="panel">
                <div className="empty-state">暂无分析结果，请等待任务完成。</div>
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
