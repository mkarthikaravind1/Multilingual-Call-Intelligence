export type CustomerMatchStatus =
  | 'matched'
  | 'not_found'
  | 'no_caller_number'
  | 'crm_not_configured'
  | 'crm_unavailable'

export type MessagingChannel = 'sms' | 'whatsapp'

export type ConsentStatus = 'granted' | 'revoked' | 'unknown'

export interface CustomerProfileDto {
  customer_id: string
  name: string
  phone_number: string
  email: string | null
  preferred_channel: MessagingChannel
  consent_status: ConsentStatus
  language: string | null
}

export interface VehicleDto {
  vehicle_id: string
  registration_number: string
  make: string
  model: string
  year: number | null
  vin: string | null
}

export interface ServiceRecordDto {
  service_id: string
  vehicle_id: string
  service_date: string
  description: string
  dealer: string | null
  odometer_km: number | null
}

export interface CallCustomerDto {
  call_id: string
  status: CustomerMatchStatus
  caller_number: string | null
  customer: CustomerProfileDto | null
  vehicles: VehicleDto[]
  selected_vehicle_id: string | null
  // For the selected vehicle, most recent first.
  service_history: ServiceRecordDto[]
}
