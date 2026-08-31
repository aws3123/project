import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '../tests/setup'
import { FeedbackWidget } from './FeedbackWidget'

vi.mock('../utils/trace', () => ({
  getOrCreateTraceId: () => 'test-trace-id',
}))

afterEach(() => server.resetHandlers())

describe('FeedbackWidget', () => {
  const defaultProps = {
    taskId: 'task-1',
    sessionId: 'session-1',
  }

  it('renders prompt and thumbs buttons', () => {
    render(<FeedbackWidget {...defaultProps} />)
    expect(screen.getByTestId('feedback-widget')).toBeInTheDocument()
    expect(screen.getByText('这个结果对您有帮助吗？')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-thumbs-up')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-thumbs-down')).toBeInTheDocument()
  })

  it('shows detail form after selecting thumbs up', () => {
    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-up'))
    expect(screen.getByTestId('feedback-detail')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-category')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-comment')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-submit-btn')).toBeInTheDocument()
  })

  it('submits feedback and shows thanks', async () => {
    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-up'))
    fireEvent.click(screen.getByTestId('feedback-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('feedback-submitted')).toBeInTheDocument()
      expect(screen.getByText('感谢反馈！')).toBeInTheDocument()
    })
  })

  it('submits with category and comment', async () => {
    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-down'))

    fireEvent.change(screen.getByTestId('feedback-category'), { target: { value: '结果不准确' } })
    fireEvent.change(screen.getByTestId('feedback-comment'), { target: { value: '测试评论' } })
    fireEvent.click(screen.getByTestId('feedback-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('feedback-submitted')).toBeInTheDocument()
    })
  })

  it('shows error on submit failure', async () => {
    server.use(
      http.post('/api/feedback/submit', async () => {
        return HttpResponse.json({ message: '服务器错误' }, { status: 500 })
      }),
    )

    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-up'))
    fireEvent.click(screen.getByTestId('feedback-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('feedback-error')).toBeInTheDocument()
      expect(screen.getByText('服务器错误')).toBeInTheDocument()
    })
  })
})
