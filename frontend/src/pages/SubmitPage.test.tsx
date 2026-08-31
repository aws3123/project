import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../tests/setup'
import { SubmitPage } from './SubmitPage'
import { useResultStore } from '../store/resultStore'
import { useTaskStore } from '../store/taskStore'

function renderSubmitPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<SubmitPage />} />
          <Route path="/code-review/:taskId" element={<div>code review detail page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SubmitPage', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_KEY', 'test-api-key')
    useResultStore.getState().clear()
    useTaskStore.getState().clear()
  })

  it('navigates to code review page when auto dispatch resolves sync', async () => {
    renderSubmitPage()

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

    expect(await screen.findByText('code review detail page')).toBeInTheDocument()
  })

  it('navigates to code review page when auto dispatch resolves async', async () => {
    renderSubmitPage()

    fireEvent.change(screen.getByLabelText('项目 ID'), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByLabelText('PR 链接'), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByLabelText('Diff 内容'), {
      target: { value: 'diff --git a/backend/src/main/java/App.java b/backend/src/main/java/App.java' },
    })
    fireEvent.click(screen.getByLabelText('自动判断（根据问题内容和改动规模自动选择）'))
    fireEvent.change(screen.getByLabelText('审查问题'), {
      target: { value: '请全面检查数据库和接口风险' },
    })

    fireEvent.click(screen.getByText('提交审查'))

    expect(await screen.findByText('code review detail page')).toBeInTheDocument()
  })

  it('submits sync review and navigates to code review page', async () => {
    renderSubmitPage()

    fireEvent.change(screen.getByRole('textbox', { name: '项目 ID' }), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByRole('textbox', { name: '项目名称' }), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'PR 链接' }), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Diff 内容' }), {
      target: { value: 'diff --git a/src/App.tsx b/src/App.tsx' },
    })

    fireEvent.click(screen.getByRole('button', { name: '提交审查' }))

    expect(await screen.findByText('code review detail page')).toBeInTheDocument()
  })

  it('submits async review and navigates to code review page', async () => {
    renderSubmitPage()

    fireEvent.click(screen.getByRole('radio', { name: '异步审查（返回 taskId 后轮询）' }))
    fireEvent.change(screen.getByRole('textbox', { name: '项目 ID' }), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByRole('textbox', { name: '项目名称' }), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'PR 链接' }), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Diff 内容' }), {
      target: { value: 'diff --git a/src/App.tsx b/src/App.tsx' },
    })

    fireEvent.click(screen.getByRole('button', { name: '提交审查' }))

    expect(await screen.findByText('code review detail page')).toBeInTheDocument()
  })

  it('shows validation error when required fields are empty', async () => {
    renderSubmitPage()

    fireEvent.click(screen.getByRole('button', { name: '提交审查' }))

    expect(await screen.findByText('请完整填写项目 ID、项目名称、PR 链接与 Diff 内容')).toBeInTheDocument()
  })

  it('shows validation error when auto mode has no question', async () => {
    renderSubmitPage()

    fireEvent.click(screen.getByRole('radio', { name: '自动判断（根据问题内容和改动规模自动选择）' }))
    fireEvent.change(screen.getByRole('textbox', { name: '项目 ID' }), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByRole('textbox', { name: '项目名称' }), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'PR 链接' }), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Diff 内容' }), {
      target: { value: 'diff --git a/src/App.tsx b/src/App.tsx' },
    })

    fireEvent.click(screen.getByRole('button', { name: '提交审查' }))

    expect(await screen.findByText('自动判断模式下必须填写审查问题')).toBeInTheDocument()
  })

  it('shows error message when API returns 500', async () => {
    server.use(
      http.post('/api/review/sync', async () =>
        HttpResponse.json({ message: 'Internal Server Error' }, { status: 500 }),
      ),
    )

    renderSubmitPage()

    fireEvent.change(screen.getByRole('textbox', { name: '项目 ID' }), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByRole('textbox', { name: '项目名称' }), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'PR 链接' }), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Diff 内容' }), {
      target: { value: 'diff --git a/src/App.tsx b/src/App.tsx' },
    })

    fireEvent.click(screen.getByRole('button', { name: '提交审查' }))

    expect(await screen.findByText('Internal Server Error')).toBeInTheDocument()
  })

  it('shows loading state on submit button during submission', async () => {
    server.use(
      http.post('/api/review/async', async () => {
        await delay(100)
        return HttpResponse.json({ taskId: 'task_loading_1', status: 'QUEUED' })
      }),
    )

    renderSubmitPage()

    fireEvent.click(screen.getByRole('radio', { name: '异步审查（返回 taskId 后轮询）' }))
    fireEvent.change(screen.getByRole('textbox', { name: '项目 ID' }), { target: { value: 'project-x' } })
    fireEvent.change(screen.getByRole('textbox', { name: '项目名称' }), { target: { value: 'Project X' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'PR 链接' }), { target: { value: 'https://example.com/pr/1' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Diff 内容' }), {
      target: { value: 'diff --git a/src/App.tsx b/src/App.tsx' },
    })

    fireEvent.click(screen.getByRole('button', { name: '提交审查' }))

    const loadingButton = screen.getByRole('button', { name: '提交中…' })
    expect(loadingButton).toBeInTheDocument()
    expect(loadingButton).toBeDisabled()

    await screen.findByText('code review detail page')
  })
})
