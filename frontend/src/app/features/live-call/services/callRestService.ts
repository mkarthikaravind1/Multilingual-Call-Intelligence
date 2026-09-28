import { apiClient } from '../../../api/client'

import type {
  CallAnalysisResponseDto,
  CallListResponseDto,
  CallResponseDto,
  CallStatsResponseDto,
  CompleteCallRequestDto,
  UtteranceRequestDto,
} from '../types/dto'

export interface StartCallRequest {
  call_id: string
  start_time?: number
}

export class CallRestService {
  startCall(request: StartCallRequest) {
    return apiClient.post<CallResponseDto>(
      '/api/v1/calls',
      request,
    )
  }

  // Always a fresh ID: the backend overwrites a call that is started with
  // an existing call_id, so user-typed IDs are never used to create calls.
  startManualCall() {
    return this.startCall({
      call_id: `manual-${crypto.randomUUID()}`,
      start_time: Date.now() / 1000,
    })
  }

  listCalls(limit: number, offset: number) {
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    })
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

  getAnalysis(callId: string) {
    return apiClient.get<CallAnalysisResponseDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}/analysis`,
    )
  }

  completeCall(
    callId: string,
    request: CompleteCallRequestDto,
  ) {
    return apiClient.post<CallResponseDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}/complete`,
      request,
    )
  }
}

export const callRestService = new CallRestService()