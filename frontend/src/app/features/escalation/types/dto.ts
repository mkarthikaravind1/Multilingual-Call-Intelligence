export type EscalationLevel = 'watch' | 'high' | 'critical'

export type EscalationStatus = 'open' | 'acknowledged' | 'resolved'

export type EscalationSignalType =
  | 'manager_request'
  | 'legal_threat'
  | 'public_complaint'
  | 'cancellation'
  | 'negative_tone'
  | 'unresolved_complaints'
  | 'other'

export interface EscalationSignalDto {
  signal_type: EscalationSignalType
  level: EscalationLevel
  description: string
  // What the customer said, when relevant.
  evidence: string | null
}

export interface EscalationDto {
  call_id: string
  // Only rises during a call.
  level: EscalationLevel
  status: EscalationStatus
  signals: EscalationSignalDto[]
  first_detected_at: number
  updated_at: number
  acknowledged_by: string | null
  acknowledged_at: number | null
  resolved_by: string | null
  resolved_at: number | null
  resolution_note: string | null
}
