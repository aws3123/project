import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ReviewSubmitForm } from '../components/ReviewSubmitForm'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { getLastAsyncReviewRequest, getLastDispatchReviewRequest, resetCapturedRequests } from './msw/handlers'

const queryClient = new QueryClient()

describe('ReviewSubmitForm', () => {
  beforeEach(() => {
    resetCapturedRequests()
    vi.stubEnv('VITE_API_KEY', 'test-api-key')
  })

  it('submits async request with backend payload mapping and api key header', async () => {
    const onSubmitted = vi.fn()
    render(
      <QueryClientProvider client={queryClient}>
        <ReviewSubmitForm onSubmitted={onSubmitted} />
      </QueryClientProvider>,
    )

    fireEvent.change(screen.getByLabelText('项目 ID'), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByLabelText('PR 链接'), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByLabelText('Diff 内容'), { target: { value: 'diff' } })
    fireEvent.click(screen.getByLabelText('异步审查（返回 taskId 后轮询）'))

    fireEvent.click(screen.getByText('提交审查'))

    await waitFor(() => {
      expect(onSubmitted).toHaveBeenCalledWith({
        sourceMode: 'async',
        resolvedMode: 'async',
        taskId: 'task_mock_1',
      })
    })

    const captured = getLastAsyncReviewRequest()
    expect(captured).not.toBeNull()
    expect(captured).toMatchObject({
      projectId: 'project-x',
      projectName: 'Project X',
      prUrl: 'https://example.com/pr/1',
      diffContent: 'diff',
      mode: 'ASYNC',
      apiKeyHeader: 'test-api-key',
    })

    expect(screen.getByText(/Trace ID:/)).toBeInTheDocument()
  })

  it('submits auto request with question and dispatch payload mapping', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <ReviewSubmitForm onSubmitted={vi.fn()} />
      </QueryClientProvider>,
    )

    fireEvent.change(screen.getByLabelText('项目 ID'), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByLabelText('PR 链接'), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByLabelText('Diff 内容'), {
      target: { value: 'diff --git a/frontend/src/App.tsx b/frontend/src/App.tsx' },
    })
    fireEvent.click(screen.getByLabelText('自动判断（根据问题内容和改动规模自动选择）'))
    fireEvent.change(screen.getByLabelText('审查问题'), {
      target: { value: '帮我快速判断这个改动有没有明显风险' },
    })

    fireEvent.click(screen.getByText('提交审查'))

    await waitFor(() => {
      expect(getLastDispatchReviewRequest()).toMatchObject({
        projectId: 'project-x',
        projectName: 'Project X',
        prUrl: 'https://example.com/pr/1',
        diffContent: 'diff --git a/frontend/src/App.tsx b/frontend/src/App.tsx',
        question: '帮我快速判断这个改动有没有明显风险',
        apiKeyHeader: 'test-api-key',
      })
    })
  })

  it('requires question when auto mode is selected', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <ReviewSubmitForm onSubmitted={vi.fn()} />
      </QueryClientProvider>,
    )

    fireEvent.click(screen.getByLabelText('自动判断（根据问题内容和改动规模自动选择）'))
    fireEvent.click(screen.getByText('提交审查'))

    expect(await screen.findByText('自动判断模式下必须填写审查问题')).toBeInTheDocument()
  })
})
