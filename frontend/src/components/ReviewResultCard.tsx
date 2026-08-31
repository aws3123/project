import type { ReviewResult } from '../types/review'
import { ReportDownloadButton } from './ReportDownloadButton'

interface ReviewResultCardProps {
  result: ReviewResult
}

export function ReviewResultCard({ result }: ReviewResultCardProps) {
  const score = Number.isFinite(result.riskScore) ? result.riskScore : 0

  return (
    <div className="result-card">
      <div className="result-card-header">
        <div>
          <h3>审查结果</h3>
          {result.riskSummary && <p className="result-card-summary">{result.riskSummary}</p>}
        </div>
        <ReportDownloadButton reportUrl={result.reportUrl} />
      </div>

      <div className="risk-score-panel">
        <span className="risk-score-label">风险评分</span>
        <div className="risk-score">
          <strong>{score.toFixed(0)}</strong>
          <span>/ 100</span>
        </div>
        {result.needHumanReview && <span className="risk-flag need-review">需要人工复核</span>}
      </div>
      {result.errorCode && <p className="error-text">错误码：{result.errorCode}</p>}
      {result.errorMessage && <p className="error-text">{result.errorMessage}</p>}

      <h4>风险维度</h4>
      {!result.riskBreakdown.length ? (
        <div className="empty-state">暂无维度细分数据</div>
      ) : (
        <ul className="risk-breakdown">
          {result.riskBreakdown.map((item) => {
            const safeScore = Math.max(0, Math.min(100, item.score)) / 100
            return (
              <li key={item.dimension} className="risk-item">
                <div className="risk-item-row">
                  <strong>{item.dimension}</strong>
                  <span>{item.score}</span>
                </div>
                <div className="risk-bar">
                  <div className="risk-bar-fill" style={{ width: `${safeScore * 100}%` }} />
                </div>
                <p>{item.description}</p>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
