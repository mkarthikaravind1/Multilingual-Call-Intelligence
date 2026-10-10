import { apiClient } from '../../../api/client'

import type {
  CreateLocationDto,
  CreateUserDto,
  LocationDto,
  ManagedUserDto,
  PostCallRepairStatusDto,
  RepairRunDto,
  RetryPostCallDto,
  UpdateLocationDto,
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

  listLocations(): Promise<LocationDto[]> {
    return apiClient.get<LocationDto[]>(`${basePath}/locations`)
  },

  createLocation(payload: CreateLocationDto): Promise<LocationDto> {
    return apiClient.post<LocationDto>(`${basePath}/locations`, payload)
  },

  updateLocation(locationId: string, payload: UpdateLocationDto): Promise<LocationDto> {
    return apiClient.request<LocationDto>(
      `${basePath}/locations/${encodeURIComponent(locationId)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    )
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
