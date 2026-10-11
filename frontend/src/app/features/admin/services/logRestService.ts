import { apiClient } from '../../../api/client'

import type {
  AiLogDto,
  AiLogEntryDetailDto,
  AiLogFilters,
  AuditLogDto,
  AuditLogFilters,
} from '../types/logs'

const basePath = '/api/v1/admin'

function toQuery(values: Array<[string, string | number | boolean | undefined]>): string {
  const query = new URLSearchParams()
  for (const [name, value] of values) {
    if (value !== undefined && value !== '') query.set(name, String(value))
  }
  return query.toString()
}

// Administrators only. Every read here is itself put in the audit log.
export const logRestService = {
  getAuditLog(filters: AuditLogFilters, limit: number, offset: number): Promise<AuditLogDto> {
    const query = toQuery([
      ['user_id', filters.userId],
      ['action', filters.action],
      ['succeeded', filters.succeeded],
      ['target_id', filters.targetId],
      ['occurred_from', filters.occurredFrom],
      ['occurred_to', filters.occurredTo],
      ['limit', limit],
      ['offset', offset],
    ])
    return apiClient.get<AuditLogDto>(`${basePath}/audit-log?${query}`)
  },

  getAiLog(filters: AiLogFilters, limit: number, offset: number): Promise<AiLogDto> {
    const query = toQuery([
      ['call_id', filters.callId],
      ['task', filters.task],
      ['outcome', filters.outcome],
      ['started_from', filters.startedFrom],
      ['started_to', filters.startedTo],
      ['limit', limit],
      ['offset', offset],
    ])
    return apiClient.get<AiLogDto>(`${basePath}/ai-log?${query}`)
  },

  // One request with what the AI was asked and what it answered.
  getAiLogEntry(entryId: string): Promise<AiLogEntryDetailDto> {
    return apiClient.get<AiLogEntryDetailDto>(
      `${basePath}/ai-log/${encodeURIComponent(entryId)}`,
    )
  },
}
