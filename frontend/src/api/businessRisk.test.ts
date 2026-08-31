import { describe, expect, it, vi } from 'vitest'
import { submitBusinessRiskSourceForm } from './businessRisk'
import { http } from './client'

vi.mock('./client', () => ({
  http: vi.fn(async () => ({ taskId: 'biz-risk-1', status: 'PENDING', sessionId: 'session-biz-risk-1', traceId: 'trace-biz-risk-1' })),
}))

const mockedHttp = vi.mocked(http)

describe('submitBusinessRiskSourceForm', () => {
  it('sends metadata and repeated files fields in multipart form data', async () => {
    const fileA = new File(['class A {}'], 'A.java', { type: 'text/x-java-source' })
    const fileB = new File(['class B {}'], 'B.java', { type: 'text/x-java-source' })

    await submitBusinessRiskSourceForm(
      {
        metadata: {
          schemaVersion: '2.0',
          projectId: 'ticket-demo',
          repo: 'ticket-service',
          branch: 'main',
          traceId: 'trace-1',
        },
        files: [fileA, fileB],
      },
      'trace-1',
    )

    expect(mockedHttp).toHaveBeenCalledTimes(1)
    const [path, options] = mockedHttp.mock.calls[0]
    expect(path).toBe('/api/business-risk/source')
    expect(options?.method).toBe('POST')
    expect(options?.traceId).toBe('trace-1')
    expect(options?.body).toBeInstanceOf(FormData)

    const formData = options?.body as FormData
    expect(formData.get('metadata')).toBe(JSON.stringify({
      schemaVersion: '2.0',
      projectId: 'ticket-demo',
      repo: 'ticket-service',
      branch: 'main',
      traceId: 'trace-1',
    }))
    expect(formData.getAll('files')).toHaveLength(2)
    expect((formData.getAll('files')[0] as File).name).toBe('A.java')
    expect((formData.getAll('files')[1] as File).name).toBe('B.java')
  })
})
