import { useNavigate } from 'react-router-dom'
import { ReviewSubmitForm } from '../components/ReviewSubmitForm'
import type { SubmissionMode } from '../types/review'

export function SubmitPage() {
  const navigate = useNavigate()

  function handleSubmitted({
    taskId,
  }: {
    sourceMode: SubmissionMode
    taskId: string
  }) {
    navigate(`/code-review/${taskId}`)
  }

  return (
    <section className="page-shell">
      <div className="panel">
        <h2 className="page-title">提交 PR 进行审查</h2>
        <p className="page-desc">支持手动同步、手动异步和自动判断三种模式。自动判断会根据问题内容与改动规模选择最快的安全执行路径。</p>
      </div>
      <div className="panel">
        <ReviewSubmitForm onSubmitted={handleSubmitted} />
      </div>
    </section>
  )
}
