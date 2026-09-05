import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchFeedbackExport, fetchFeedbackStats, type FeedbackExportParams } from '../api/feedback'
import type { FeedbackExportItem, FeedbackStatsResponse } from '../types/feedback'

const PAGE_SIZE = 10

type RangeKey = '7d' | '30d'
type SourceFilter = 'all' | 'review' | 'business_risk'

const rangeOptions: { key: RangeKey; label: string; days: number }[] = [
  { key: '7d', label: '近 7 天', days: 7 },
  { key: '30d', label: '近 30 天', days: 30 },
]

const sourceOptions: { key: SourceFilter; label: string }[] = [
  { key: 'all', label: '全部来源' },
  { key: 'review', label: '代码审查' },
  { key: 'business_risk', label: '业务风险' },
]

function resolveRange(days: number) {
  const to = new Date()
  const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000)
  return { from, to }
}

function getTaskLink(item: FeedbackExportItem) {
  if (item.source === 'business_risk') {
    return `/business-risk/${item.taskId}`
  }
  return `/code-review/${item.taskId}`
}

export function FeedbackDashboardPage() {
  const [rangeKey, setRangeKey] = useState<RangeKey>('7d')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')

  const [stats, setStats] = useState<FeedbackStatsResponse | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)

  const [items, setItems] = useState<FeedbackExportItem[]>([])
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(0)
  const [total, setTotal] = useState(0)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)

  const range = useMemo(() => {
    const option = rangeOptions.find((o) => o.key === rangeKey) ?? rangeOptions[0]
    return resolveRange(option.days)
  }, [rangeKey])

  const source = sourceFilter === 'all' ? undefined : sourceFilter

  const loadStats = useCallback(() => {
    setStatsLoading(true)
    setStatsError(null)
    fetchFeedbackStats({ from: range.from, to: range.to, source })
      .then((res) => {
        setStats(res)
        setStatsLoading(false)
      })
      .catch((err) => {
        setStatsError(err.message ?? '加载失败')
        setStatsLoading(false)
      })
  }, [range, source])

  useEffect(() => {
    loadStats()
  }, [loadStats])

  useEffect(() => {
    setPage(1)
  }, [rangeKey, sourceFilter])

  const loadList = useCallback((p: number) => {
    const params: FeedbackExportParams = { from: range.from, to: range.to, source, page: p, size: PAGE_SIZE }
    setListLoading(true)
    setListError(null)
    fetchFeedbackExport(params)
      .then((res) => {
        setItems(res.records ?? [])
        setPages(res.pages ?? 0)
        setTotal(res.total ?? 0)
        setPage(res.current ?? p)
        setListLoading(false)
      })
      .catch((err) => {
        setListError(err.message ?? '加载失败')
        setListLoading(false)
      })
  }, [range, source])

  useEffect(() => {
    loadList(page)
  }, [loadList, page])

  const maxDaily = useMemo(() => {
    if (!stats?.daily_breakdown?.length) return 0
    return Math.max(
      ...stats.daily_breakdown.map((d) => d.thumbs_up + d.thumbs_down),
      1,
    )
  }, [stats])

  const ratioPercent = stats ? Math.round(Number(stats.ratio) * 100) : 0

  return (
    <section className="page-shell">
      <div className="page-intro">
        <h2 className="page-title">反馈统计</h2>
        <p className="page-desc">用户赞/踩反馈的好评率、日趋势与差评明细</p>
      </div>

      <div className="panel feedback-filter-bar">
        <div className="feedback-filter-group" role="group" aria-label="时间范围">
          {rangeOptions.map((option) => (
            <button
              key={option.key}
              className={`task-type-tab${rangeKey === option.key ? ' is-active' : ''}`}
              onClick={() => setRangeKey(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="feedback-filter-group" role="group" aria-label="来源筛选">
          {sourceOptions.map((option) => (
            <button
              key={option.key}
              className={`task-type-tab${sourceFilter === option.key ? ' is-active' : ''}`}
              onClick={() => setSourceFilter(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {statsError ? (
        <div className="panel empty-state">统计加载失败：{statsError}</div>
      ) : (
        <div className="feedback-stats-grid">
          <div className="panel feedback-stat-card" data-testid="feedback-stat-total">
            <span className="feedback-stat-label">总反馈</span>
            <span className="feedback-stat-value">{statsLoading ? '…' : stats?.total ?? 0}</span>
          </div>
          <div className="panel feedback-stat-card up" data-testid="feedback-stat-up">
            <span className="feedback-stat-label">👍 有帮助</span>
            <span className="feedback-stat-value">{statsLoading ? '…' : stats?.thumbs_up ?? 0}</span>
          </div>
          <div className="panel feedback-stat-card down" data-testid="feedback-stat-down">
            <span className="feedback-stat-label">👎 没帮助</span>
            <span className="feedback-stat-value">{statsLoading ? '…' : stats?.thumbs_down ?? 0}</span>
          </div>
          <div className="panel feedback-stat-card ratio" data-testid="feedback-stat-ratio">
            <span className="feedback-stat-label">好评率</span>
            <span className="feedback-stat-value">{statsLoading ? '…' : `${ratioPercent}%`}</span>
          </div>
        </div>
      )}

      <div className="panel">
        <h3 className="feedback-section-title">日趋势</h3>
        {!stats?.daily_breakdown?.length ? (
          <div className="empty-state">所选时间范围内暂无反馈数据。</div>
        ) : (
          <div className="feedback-trend" data-testid="feedback-trend">
            {stats.daily_breakdown.map((day) => {
              const dayTotal = day.thumbs_up + day.thumbs_down
              const upPct = dayTotal > 0 ? (day.thumbs_up / dayTotal) * 100 : 0
              const downPct = dayTotal > 0 ? (day.thumbs_down / dayTotal) * 100 : 0
              const heightPct = (dayTotal / maxDaily) * 100
              return (
                <div key={day.date} className="feedback-trend-item" title={`${day.date}：👍 ${day.thumbs_up} / 👎 ${day.thumbs_down}`}>
                  <div className="feedback-trend-bar-wrapper">
                    <div className="feedback-trend-bar" style={{ height: `${Math.max(heightPct, dayTotal > 0 ? 4 : 0)}%` }}>
                      <div className="feedback-trend-seg up" style={{ height: `${upPct}%` }} />
                      <div className="feedback-trend-seg down" style={{ height: `${downPct}%` }} />
                    </div>
                  </div>
                  <span className="feedback-trend-date">{day.date.slice(5)}</span>
                </div>
              )
            })}
          </div>
        )}
        <div className="feedback-trend-legend">
          <span className="legend-dot up" /> 有帮助
          <span className="legend-dot down" /> 没帮助
        </div>
      </div>

      <div className="panel">
        <h3 className="feedback-section-title">反馈明细</h3>
        <div className="feedback-list-header">
          <span>共 {total} 条 — 第 {page} / {pages || 1} 页</span>
        </div>

        {listError ? (
          <div className="empty-state">明细加载失败：{listError}</div>
        ) : listLoading ? (
          <div className="empty-state">加载中...</div>
        ) : items.length === 0 ? (
          <div className="empty-state">所选时间范围内暂无反馈记录。</div>
        ) : (
          <div className="feedback-table-wrap">
            <table className="feedback-table" data-testid="feedback-table">
              <thead>
                <tr>
                  <th>任务 ID</th>
                  <th>类型</th>
                  <th>来源</th>
                  <th>分类</th>
                  <th>意见</th>
                  <th>traceId</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link className="task-link" to={getTaskLink(item)}>
                        {item.taskId}
                      </Link>
                    </td>
                    <td>{item.feedbackType === 'thumbs_up' ? '👍' : '👎'}</td>
                    <td>{item.source === 'business_risk' ? '业务风险' : '代码审查'}</td>
                    <td>{item.category ?? '—'}</td>
                    <td className="feedback-comment-cell" title={item.comment ?? ''}>
                      {item.comment ? (item.comment.length > 40 ? `${item.comment.slice(0, 40)}…` : item.comment) : '—'}
                    </td>
                    <td className="feedback-trace-cell" title={item.traceId ?? ''}>{item.traceId ?? '—'}</td>
                    <td>{item.createdAt ? new Date(item.createdAt).toLocaleString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {pages > 1 && (
          <div className="pagination">
            <button
              className="pagination-btn"
              disabled={page <= 1 || listLoading}
              onClick={() => setPage(page - 1)}
            >
              上一页
            </button>
            <span className="pagination-info">
              {page} / {pages}
            </span>
            <button
              className="pagination-btn"
              disabled={page >= pages || listLoading}
              onClick={() => setPage(page + 1)}
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
