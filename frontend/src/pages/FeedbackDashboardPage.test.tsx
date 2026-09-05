import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../tests/setup'
import { FeedbackDashboardPage } from './FeedbackDashboardPage'

afterEach(() => server.resetHandlers())

function renderPage() {
  return render(
    <MemoryRouter>
      <FeedbackDashboardPage />
    </MemoryRouter>,
  )
}

describe('FeedbackDashboardPage', () => {
  it('renders stat cards from stats endpoint', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('feedback-stat-total')).toHaveTextContent('8')
    })
    expect(screen.getByTestId('feedback-stat-up')).toHaveTextContent('6')
    expect(screen.getByTestId('feedback-stat-down')).toHaveTextContent('2')
    expect(screen.getByTestId('feedback-stat-ratio')).toHaveTextContent('75%')
  })

  it('renders daily trend bars', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('feedback-trend')).toBeInTheDocument()
    })
    expect(screen.getByTestId('feedback-trend').children.length).toBe(2)
  })

  it('renders feedback detail rows with links and trace ids', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('feedback-table')).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: 'task-down-1' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'task-up-1' })).toBeInTheDocument()
    expect(screen.getByText('误报')).toBeInTheDocument()
    expect(screen.getByText('trace-111')).toBeInTheDocument()
  })

  it('filters by business_risk source', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('feedback-stat-total')).toHaveTextContent('8')
    })

    fireEvent.click(screen.getByRole('button', { name: '业务风险' }))

    await waitFor(() => {
      expect(screen.getByTestId('feedback-stat-total')).toHaveTextContent('4')
    })
    expect(screen.getByTestId('feedback-stat-down')).toHaveTextContent('3')

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'task-biz-down' })).toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: 'task-down-1' })).not.toBeInTheDocument()
  })

  it('shows empty state when no feedback data', async () => {
    server.use(
      http.get('/api/feedback/stats', () =>
        HttpResponse.json({
          total: 0,
          thumbs_up: 0,
          thumbs_down: 0,
          ratio: '0.00',
          daily_breakdown: [],
        }),
      ),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('所选时间范围内暂无反馈数据。')).toBeInTheDocument()
    })
  })
})
