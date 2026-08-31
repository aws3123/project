import type {
  BusinessRiskSourceSubmitResponse,
  BusinessRiskSourceUploadInput,
} from '../types/businessRisk'
import { http } from './client'

const SOURCE_ENDPOINT = '/api/business-risk/source'

export function submitBusinessRiskSourceForm(input: BusinessRiskSourceUploadInput, traceId?: string) {
  const formData = new FormData()
  formData.append('metadata', JSON.stringify(input.metadata))

  for (const file of input.files) {
    formData.append('files', file)
  }

  return http<BusinessRiskSourceSubmitResponse>(SOURCE_ENDPOINT, {
    method: 'POST',
    body: formData,
    traceId,
  })
}
