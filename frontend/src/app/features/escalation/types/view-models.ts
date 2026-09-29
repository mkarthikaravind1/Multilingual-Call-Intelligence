import type { EscalationLevel, EscalationSignalType, EscalationStatus } from './dto'

export interface EscalationSignalViewModel {
  type: EscalationSignalType
  level: EscalationLevel
  description: string
  evidence: string | null
}

export interface EscalationViewModel {
  callId: string
  level: EscalationLevel
  status: EscalationStatus
  signals: EscalationSignalViewModel[]
  firstDetectedAt: number
  updatedAt: number
  acknowledgedBy: string | null
  acknowledgedAt: number | null
  resolvedBy: string | null
  resolvedAt: number | null
  resolutionNote: string | null
}
