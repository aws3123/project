import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { TaskDashboardPage } from './TaskDashboardPage'
import { useTaskStore } from '../store/taskStore'

function renderPage() {
  return render(
    <MemoryRouter>
      <TaskDashboardPage />
    </MemoryRouter>,
  )
}

describe('TaskDashboardPage', () => {
  beforeEach(() => {
    useTaskStore.getState().clear()
  })

  it('renders empty task list shell', () => {
    renderPage()

    expect(screen.getByText('当前会话任务')).toBeInTheDocument()
    expect(screen.getByText('暂无任务。请先在“提交审查”页面创建一个任务。')).toBeInTheDocument()
  })

  it('renders task rows with metadata and links', () => {
    useTaskStore.getState().upsertTasks([
      {
        taskId: 'task-1',
        projectId: 'project-alpha',
        projectName: 'Project Alpha',
        prLink: 'https://example.com/pr/1',
        status: 'PROCESSING',
        createdAt: '2026-04-26T08:00:00.000Z',
      },
    ])

    renderPage()

    expect(screen.getByRole('link', { name: 'task-1' })).toBeInTheDocument()
    expect(screen.getByText('Project Alpha')).toBeInTheDocument()
    expect(screen.getByText(/创建于：/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看 PR' })).toHaveAttribute('href', 'https://example.com/pr/1')
  })
})
