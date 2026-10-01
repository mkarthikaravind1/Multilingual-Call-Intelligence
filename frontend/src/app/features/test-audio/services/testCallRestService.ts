import { apiClient } from '../../../api/client'

export interface StartTestCallResponseDto {
  call_id: string
  provider_call_id: string
  stream_path: string
}

const basePath = '/api/v1/test-calls'

export const testCallRestService = {
  start(fromNumber: string): Promise<StartTestCallResponseDto> {
    return apiClient.post<StartTestCallResponseDto>(basePath, { from_number: fromNumber })
  },

  end(providerCallId: string, durationSeconds: number): Promise<void> {
    return apiClient.post<void>(`${basePath}/${encodeURIComponent(providerCallId)}/end`, {
      duration_seconds: durationSeconds,
    })
  },
}
