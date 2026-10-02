import { apiClient } from '../../../api/client'

import type {
  EscalationDto,
  EscalationQueueFilters,
  EscalationQueueState,
  EscalationStatsDto,
} from '../types/dto'

const basePath = '/api/v1/escalations'

export const escalationRestService = {
  listQueue(
    state: EscalationQueueState = 'active',
    filters: EscalationQueueFilters = {},
  ): Promise<EscalationDto[]> {
    const query = new URLSearchParams({ state })
    const bounds: Array<[string, number | undefined]> = [
      ['detected_from', filters.detectedFrom],
      ['detected_to', filters.detectedTo],
      ['acknowledged_from', filters.acknowledgedFrom],
      ['acknowledged_to', filters.acknowledgedTo],
    ]
    for (const [name, value] of bounds) {
      if (value !== undefined) query.set(name, String(value))
    }
    return apiClient.get<EscalationDto[]>(`${basePath}?${query.toString()}`)
  },

  getStats(): Promise<EscalationStatsDto> {
    return apiClient.get<EscalationStatsDto>(`${basePath}/stats`)
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
