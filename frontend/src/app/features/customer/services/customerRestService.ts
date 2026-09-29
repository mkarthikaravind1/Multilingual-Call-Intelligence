import { apiClient } from '../../../api/client'

import type { CallCustomerDto } from '../types/dto'

const callPath = (callId: string) =>
  `/api/v1/calls/${encodeURIComponent(callId)}/customer`

export const customerRestService = {
  getCallCustomer(callId: string): Promise<CallCustomerDto> {
    return apiClient.get<CallCustomerDto>(callPath(callId))
  },

  identifyCustomer(callId: string, phoneNumber: string): Promise<CallCustomerDto> {
    return apiClient.request<CallCustomerDto>(callPath(callId), {
      method: 'PUT',
      body: JSON.stringify({ phone_number: phoneNumber }),
    })
  },

  selectVehicle(callId: string, vehicleId: string | null): Promise<CallCustomerDto> {
    return apiClient.request<CallCustomerDto>(`${callPath(callId)}/vehicle`, {
      method: 'PUT',
      body: JSON.stringify({ vehicle_id: vehicleId }),
    })
  },
}
