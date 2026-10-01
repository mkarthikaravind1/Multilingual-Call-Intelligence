import { apiClient } from '../../../api/client'

import type {
  CreateUserDto,
  ManagedUserDto,
  PostCallRepairStatusDto,
  RepairRunDto,
  RetryPostCallDto,
  UpdateUserDto,
} from '../types/dto'

const basePath = '/api/v1/admin'

export const adminRestService = {
  listUsers(): Promise<ManagedUserDto[]> {
    return apiClient.get<ManagedUserDto[]>(`${basePath}/users`)
  },

  createUser(payload: CreateUserDto): Promise<ManagedUserDto> {
    return apiClient.post<ManagedUserDto>(`${basePath}/users`, payload)
  },

  updateUser(userId: string, payload: UpdateUserDto): Promise<ManagedUserDto> {
    return apiClient.request<ManagedUserDto>(
      `${basePath}/users/${encodeURIComponent(userId)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    )
  },

  resetPassword(userId: string, password: string): Promise<void> {
    return apiClient.post<void>(`${basePath}/users/${encodeURIComponent(userId)}/password`, {
      password,
    })
  },

  getPostCallStatus(): Promise<PostCallRepairStatusDto> {
    return apiClient.get<PostCallRepairStatusDto>(`${basePath}/post-call`)
  },

  runPostCallRepair(): Promise<RepairRunDto> {
    return apiClient.post<RepairRunDto>(`${basePath}/post-call/repair`, {})
  },

  retryPostCall(callId: string): Promise<RetryPostCallDto> {
    return apiClient.post<RetryPostCallDto>(
      `${basePath}/post-call/${encodeURIComponent(callId)}/retry`,
      {},
    )
  },
}
