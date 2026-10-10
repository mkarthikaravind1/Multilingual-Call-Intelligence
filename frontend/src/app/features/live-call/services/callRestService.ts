import { apiClient } from '../../../api/client'

import type {
  CallAnalysisResponseDto,
  CallListResponseDto,
  CallResponseDto,
  CallStatsResponseDto,
  CompleteCallRequestDto,
  LiveTokenResponseDto,
  UtteranceRequestDto,
} from '../types/dto'

// Every field is optional; set ones must all match (see GET /api/v1/calls).
export interface CallListFilters {
  // Any of these; empty or missing means all.
  statuses?: Array<'active' | 'completed'>
  // High or critical escalations, open or resolved.
  highEscalation?: boolean
  // Part of the customer name or vehicle registration.
  customer?: string
  // Digits that appear in the caller's number.
  phone?: string
  // Epoch seconds; from inclusive, to exclusive.
  startedFrom?: number
  startedTo?: number
  resolvedFrom?: number
  resolvedTo?: number
}

export interface StartCallRequest {
  call_id: string
  // null: the server's clock (the browser's may be wrong).
  start_time?: number | null
}

export class CallRestService {
  startCall(request: StartCallRequest) {
    return apiClient.post<CallResponseDto>(
      '/api/v1/calls',
      request,
    )
  }

  // Always a fresh ID: the backend rejects (409) a call_id that is already
  // in use, so user-typed IDs are never used to create calls.
  startManualCall() {
    return this.startCall({
      call_id: `manual-${crypto.randomUUID()}`,
      start_time: null,
    })
  }

  listCalls(limit: number, offset: number, filters: CallListFilters = {}) {
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    })
    filters.statuses?.forEach((status) => query.append('status', status))
    if (filters.highEscalation) query.set('high_escalation', 'true')
    if (filters.customer?.trim()) query.set('customer', filters.customer.trim())
    if (filters.phone?.trim()) query.set('phone', filters.phone.trim())
    const bounds: Array<[string, number | undefined]> = [
      ['started_from', filters.startedFrom],
      ['started_to', filters.startedTo],
      ['resolved_from', filters.resolvedFrom],
      ['resolved_to', filters.resolvedTo],
    ]
    for (const [name, value] of bounds) {
      if (value !== undefined) query.set(name, String(value))
    }
    return apiClient.get<CallListResponseDto>(
      `/api/v1/calls?${query.toString()}`,
    )
  }

  getCallStats() {
    return apiClient.get<CallStatsResponseDto>(
      '/api/v1/call-stats',
    )
  }

  getCall(callId: string) {
    return apiClient.get<CallResponseDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}`,
    )
  }

  submitUtterance(
    callId: string,
    request: UtteranceRequestDto,
  ) {
    return apiClient.post<CallAnalysisResponseDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}/utterances`,
      request,
    )
  }

  // A single-use, short-lived ticket for opening the call's live
  // WebSocket, so the access token never appears in a URL.
  createLiveToken(callId: string) {
    return apiClient.post<LiveTokenResponseDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}/live-token`,
      {},
    )
  }

  getAnalysis(callId: string) {
    return apiClient.get<CallAnalysisResponseDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}/analysis`,
    )
  }

  // The server sets the end time from its own clock.
  completeCall(
    callId: string,
    request: CompleteCallRequestDto = {},
  ) {
    return apiClient.post<CallResponseDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}/complete`,
      request,
    )
  }
}

export const callRestService = new CallRestService()