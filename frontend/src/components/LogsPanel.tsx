import type { ReviewLogEntry } from '../types/review'

interface LogsPanelProps {
  logs: ReviewLogEntry[]
}

export function LogsPanel({ logs }: LogsPanelProps) {
  if (!logs.length) {
    return <div className="empty-state">暂无日志</div>
  }

  return (
    <div className="logs-panel">
      <div className="logs-panel-header">
        <h4>LangGraph 节点日志</h4>
        <p className="page-desc">按节点顺序展示状态、耗时与输入输出摘要。</p>
      </div>
      <ol>
        {logs.map((log) => (
          <li key={`${log.node}-${log.timestamp}`}>
            <div className="log-item-header">
              <strong>{log.node}</strong>
              <span className="trace-text">
                {log.status} · {log.durationMs}ms
              </span>
            </div>
            <div className="log-item-meta">
              <div>输入：{log.inputSummary}</div>
              <div>输出：{log.outputSummary}</div>
              <div>时间：{log.timestamp}</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
