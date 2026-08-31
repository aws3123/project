import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TaskStatusBadge } from '../components/TaskStatusBadge'
import { fetchTaskList, type TaskListItem } from '../api/task'

const PAGE_SIZE = 5

type TypeFilter = 'all' | 'code_review' | 'business_risk'

function toStoreTask(item: TaskListItem) {
  return {
    taskId: item.taskId ?? '',
    projectId: item.projectId,
    projectName: item.projectName,
    status: item.status as never,
    mode: item.mode as never,
    prLink: item.prUrl,
    createdAt: item.createdAt ?? new Date().toISOString(),
    updatedAt: item.updatedAt,
  }
}

function getTaskLink(task: { taskId: string; mode?: string }) {
  if (task.mode === 'business_risk_source') {
    return `/business-risk/${task.taskId}`
  }
  return `/code-review/${task.taskId}`
}

const typeFilterTabs: { key: TypeFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'code_review', label: '代码审查' },
  { key: 'business_risk', label: '业务风险' },
]

export function TaskDashboardPage() {
  const [items, setItems] = useState<ReturnType<typeof toStoreTask>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [filterProjectId, setFilterProjectId] = useState('')
  const [searchText, setSearchText] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')

  const loadPage = useCallback((p: number, projectId: string) => {
    setLoading(true)
    setError(null)
    fetchTaskList({ page: p, size: PAGE_SIZE, projectId: projectId || undefined })
      .then((res) => {
        setItems(res.items.map(toStoreTask))
        setTotal(res.total)
        setTotalPages(res.totalPages)
        setPage(res.page)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message ?? '加载失败')
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    loadPage(1, filterProjectId)
  }, [loadPage, filterProjectId])

  const handleSearch = () => {
    setFilterProjectId(searchText.trim())
  }

  const handleClear = () => {
    setSearchText('')
    setFilterProjectId('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch()
  }

  // Client-side type filtering
  const filteredItems = items.filter((item) => {
    if (typeFilter === 'all') return true
    if (typeFilter === 'business_risk') return item.mode === 'business_risk_source'
    // code_review: everything that is not business_risk_source
    return item.mode !== 'business_risk_source'
  })

  return (
    <section className="page-shell">
      <div className="page-intro">
        <h2 className="page-title">任务查询</h2>
        <p className="page-desc">所有已提交的审查任务</p>
      </div>

      <div className="panel task-list-card">
        <div className="task-type-tabs">
          {typeFilterTabs.map((tab) => (
            <button
              key={tab.key}
              className={`task-type-tab${typeFilter === tab.key ? ' is-active' : ''}`}
              onClick={() => setTypeFilter(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="task-search-bar">
          <input
            className="task-search-input"
            type="text"
            placeholder="输入项目 ID 筛选..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button className="task-search-btn" onClick={handleSearch} disabled={loading}>
            查询
          </button>
          {filterProjectId && (
            <button className="task-search-clear" onClick={handleClear}>
              清除
            </button>
          )}
        </div>

        <div className="task-list-header">
          <span>
            {loading
              ? '加载中...'
              : filterProjectId
                ? `项目 "${filterProjectId}" — ${total} 个任务`
                : `共 ${total} 个任务 — 第 ${page} / ${totalPages || 1} 页`}
          </span>
          <span className="task-list-hint">点击任务 ID 查看详情</span>
        </div>

        {error ? (
          <div className="empty-state task-list-empty">加载失败：{error}</div>
        ) : filteredItems.length === 0 && !loading ? (
          <div className="empty-state task-list-empty">
            {filterProjectId
              ? `没有找到项目 "${filterProjectId}" 的任务。`
              : typeFilter !== 'all'
                ? '当前分类下暂无任务。'
                : '暂无任务。请先在"提交审查"页面创建一个任务。'}
          </div>
        ) : (
          <div className="task-list" role="list">
            {filteredItems.map((task) => (
              <article key={task.taskId} className="task-list-item" role="listitem">
                <div className="task-list-title-row">
                  <div className="task-list-title-group">
                    <Link className="task-link" to={getTaskLink(task)}>
                      {task.taskId}
                    </Link>
                    <p className="task-list-project">{task.projectName || task.projectId}</p>
                  </div>
                  <TaskStatusBadge status={task.status} />
                </div>

                <div className="task-list-meta">
                  <span>项目 ID：{task.projectId}</span>
                  <span>创建于：{new Date(task.createdAt).toLocaleString()}</span>
                  {task.prLink ? (
                    <a href={task.prLink} target="_blank" rel="noreferrer">
                      查看 PR
                    </a>
                  ) : (
                    <span>暂无 PR 链接</span>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}

        {!filterProjectId && totalPages > 1 && (
          <div className="pagination">
            <button
              className="pagination-btn"
              disabled={page <= 1 || loading}
              onClick={() => loadPage(page - 1, filterProjectId)}
            >
              上一页
            </button>
            <span className="pagination-info">
              {page} / {totalPages}
            </span>
            <button
              className="pagination-btn"
              disabled={page >= totalPages || loading}
              onClick={() => loadPage(page + 1, filterProjectId)}
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
