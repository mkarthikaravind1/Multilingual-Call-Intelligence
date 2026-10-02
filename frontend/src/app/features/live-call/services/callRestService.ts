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

  // Always a fresh ID: the backend rejects (409) a call_id that is already
  // in use, so user-typed IDs are never used to create calls.
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