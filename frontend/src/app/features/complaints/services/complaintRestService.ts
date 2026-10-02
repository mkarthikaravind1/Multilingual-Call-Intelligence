import { apiClient } from '../../../api/client'

import type {
  CallComplaintsDto,
  ComplaintAction,
  ComplaintDto,
  ComplaintQueueFilters,
  ComplaintQueueState,
  DiscoveryRunDto,
  EmergingComplaintDto,
  EmergingComplaintStatus,
  EmergingComplaintsDto,
} from '../types/dto'

const complaintsPath = '/api/v1/complaints'
const emergingPath = '/api/v1/emerging-complaints'

const cleanNote = (note: string) => note.trim() || null

export const complaintRestService = {
  listQueue(
    state: ComplaintQueueState = 'open',
    filters: ComplaintQueueFilters = {},
  ): Promise<ComplaintDto[]> {
    const query = new URLSearchParams({ state })
    filters.categories?.forEach((category) => query.append('category', category))
    filters.stages?.forEach((stage) => query.append('stage', stage))
    return apiClient.get<ComplaintDto[]>(`${complaintsPath}?${query.toString()}`)
  },

  getCallComplaints(callId: string): Promise<CallComplaintsDto> {
    return apiClient.get<CallComplaintsDto>(
      `/api/v1/calls/${encodeURIComponent(callId)}/complaints`,
    )
  },

  updateStatus(
    complaintId: string,
    status: ComplaintAction,
    note: string,
  ): Promise<ComplaintDto> {
    return apiClient.post<ComplaintDto>(
      `${complaintsPath}/${encodeURIComponent(complaintId)}/status`,
      { status, note: cleanNote(note) },
    )
  },
}

export const emergingComplaintRestService = {
  list(status?: EmergingComplaintStatus): Promise<EmergingComplaintsDto> {
    return apiClient.get<EmergingComplaintsDto>(
      status ? `${emergingPath}?status=${status}` : emergingPath,
    )
  },

  discover(): Promise<DiscoveryRunDto> {
    return apiClient.post<DiscoveryRunDto>(`${emergingPath}/discover`, {})
  },

  review(
    candidateId: string,
    decision: EmergingComplaintStatus,
    note: string,
  ): Promise<EmergingComplaintDto> {
    return apiClient.post<EmergingComplaintDto>(
      `${emergingPath}/${encodeURIComponent(candidateId)}/review`,
      { decision, note: cleanNote(note) },
    )
  },
}
