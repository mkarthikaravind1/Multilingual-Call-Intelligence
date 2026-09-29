import { apiClient } from '../../../api/client'

import type { EscalationDto } from '../types/dto'

const basePath = '/api/v1/escalations'

export const escalationRestService = {
  listQueue(state: 'active' | 'resolved' = 'active'): Promise<EscalationDto[]> {
    return apiClient.get<EscalationDto[]>(`${basePath}?state=${state}`)
  },

  acknowledge(callId: string): Promise<EscalationDto> {
    return apiClient.post<EscalationDto>(
      `${basePath}/${encodeURIComponent(callId)}/acknowledge`,
      {},
    )
  },

  resolve(callId: string, note: string): Promise<EscalationDto> {
    return apiClient.post<EscalationDto>(
      `${basePath}/${encodeURIComponent(callId)}/resolve`,
      { note: note.trim() || null },
    )
  },
}
