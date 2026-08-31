import { TaskStatusBadge } from './TaskStatusBadge'
import type { ReviewTask } from '../types/review'

interface TaskSummarySidebarProps {
  taskId: string
  task: ReviewTask
  effectiveSessionId: string
  effectiveTraceId: string
}

export function TaskSummarySidebar({ taskId, task, effectiveSessionId, effectiveTraceId }: TaskSummarySidebarProps) {
  return (
    <aside className="task-detail-sidebar">
      <div className="panel task-summary-card">
        <h3>摘要信息</h3>
        <dl className="summary-list">
          <div className="summary-row">
            <dt>当前状态</dt>
            <dd>
              <TaskStatusBadge status={task.status} />
            </dd>
          </div>
          <div className="summary-row">
            <dt>Task ID</dt>
            <dd className="trace-text">{taskId}</dd>
          </div>
          <div className="summary-row">
            <dt>Session ID</dt>
            <dd className="trace-text">{effectiveSessionId}</dd>
          </div>
          <div className="summary-row">
            <dt>Trace ID</dt>
            <dd className="trace-text" data-testid="trace-id-value">{effectiveTraceId}</dd>
          </div>
          <div className="summary-row">
            <dt>项目 ID</dt>
            <dd>{task.projectId}</dd>
          </div>
          <div className="summary-row">
            <dt>创建时间</dt>
            <dd>{new Date(task.createdAt).toLocaleString()}</dd>
          </div>
          <div className="summary-row">
            <dt>PR 链接</dt>
            <dd>
              {task.prLink ? (
                <a href={task.prLink} target="_blank" rel="noreferrer">
                  {task.prLink}
                </a>
              ) : (
                '暂无'
              )}
            </dd>
          </div>
        </dl>
      </div>

      {task.handoffDecision && (
        <div className="panel task-summary-card">
          <h3>最近一次复核</h3>
          <dl className="summary-list">
            <div className="summary-row">
              <dt>决策</dt>
              <dd>{task.handoffDecision}</dd>
            </div>
            {task.handoffOperator && (
              <div className="summary-row">
                <dt>处理人</dt>
                <dd>{task.handoffOperator}</dd>
              </div>
            )}
            {task.handoffComment && (
              <div className="summary-row">
                <dt>备注</dt>
                <dd>{task.handoffComment}</dd>
              </div>
            )}
            {task.handoffHandledAt && (
              <div className="summary-row">
                <dt>处理时间</dt>
                <dd>{new Date(task.handoffHandledAt).toLocaleString()}</dd>
              </div>
            )}
          </dl>
        </div>
      )}
    </aside>
  )
}
