import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { submitBusinessRiskSourceForm } from '../api/businessRisk'
import { BusinessRiskSourcePage } from './BusinessRiskSourcePage'

const mockedNavigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockedNavigate,
  }
})

vi.mock('../api/businessRisk', () => ({
  submitBusinessRiskSourceForm: vi.fn(),
}))

const mockedSubmitBusinessRiskSourceForm = vi.mocked(submitBusinessRiskSourceForm)

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/business-risk/source']}>
      <Routes>
        <Route path="/business-risk/source" element={<BusinessRiskSourcePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('BusinessRiskSourcePage', () => {
  beforeEach(() => {
    mockedNavigate.mockReset()
    mockedSubmitBusinessRiskSourceForm.mockReset()
  })

  it('submits selected java files and navigates to task detail', async () => {
    mockedSubmitBusinessRiskSourceForm.mockResolvedValue({
      taskId: 'biz-risk-1',
      status: 'PENDING',
      sessionId: 'session-biz-risk-1',
      traceId: 'trace-biz-risk-1',
    })

    renderPage()

    const file = new File(['class TicketController {}'], 'TicketController.java', { type: 'text/x-java-source' })
    fireEvent.change(screen.getByLabelText('上传 .java 文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByText('提交业务风险审查'))

    await waitFor(() => expect(mockedNavigate).toHaveBeenCalledWith('/business-risk/biz-risk-1'))
    expect(mockedSubmitBusinessRiskSourceForm).toHaveBeenCalledTimes(1)
    const [payload] = mockedSubmitBusinessRiskSourceForm.mock.calls[0]
    expect(payload.metadata.projectId).toBe('ticket-demo')
    expect(payload.files.map((item) => item.name)).toEqual(['TicketController.java'])
    expect(await screen.findByText(/Trace ID：trace-biz-risk-1/)).toBeInTheDocument()
  })

  it('blocks non-java files before submit', async () => {
    renderPage()

    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('上传 .java 文件'), { target: { files: [file] } })

    expect(screen.getByText('仅支持上传 .java 文件')).toBeInTheDocument()
    expect(mockedSubmitBusinessRiskSourceForm).not.toHaveBeenCalled()
  })

  it('shows backend traceId when the upload fails with 503', async () => {
    mockedSubmitBusinessRiskSourceForm.mockRejectedValue(
      new ApiError({
        status: 503,
        message: 'worker unavailable',
        traceId: 'trace-fail-1',
      }),
    )

    renderPage()

    const file = new File(['class TicketController {}'], 'TicketController.java', { type: 'text/x-java-source' })
    fireEvent.change(screen.getByLabelText('上传 .java 文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByText('提交业务风险审查'))

    expect(await screen.findByText('服务暂时不可用，请稍后重试（traceId: trace-fail-1）')).toBeInTheDocument()
  })
})
