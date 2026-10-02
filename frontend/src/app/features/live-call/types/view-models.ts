import type { EscalationLevel, EscalationStatus } from '../../escalation/types/dto'
import type { EscalationViewModel } from '../../escalation/types/view-models'

export interface TranscriptTurnViewModel {
  utteranceId: string
  transcript: string
  speakerRole: string
  languages: string[]
  startTime: number
  endTime: number
  confidence: number | null
}

export interface ComplaintViewModel {
  category: string
  status: string
}

export interface SentimentViewModel {
  label: string
  confidence: number
  evidence: string
}

export interface QuestionSuggestionViewModel {
  question: string
  targetCategory: string
  priority: number
  reason: string
  source: string
  confidence: number | null
}

export interface CallMetadataViewModel {
  callId: string
  status: string
  startTime: number
  endTime: number | null
  utteranceCount: number
  escalationLevel: EscalationLevel | null
  escalationStatus: EscalationStatus | null
  callerNumber: string | null
  customerName: string | null
  vehicleRegistration: string | null
  complaintsResolvedAt: number | null
}

// Monetary values are kept as the backend's Decimal strings; never recalculated here.
export interface EstimatedPartViewModel {
  name: string
  quantity: number
  unitPrice: string
  totalPrice: string
}

export interface LabourEstimateViewModel {
  hours: number
  hourlyRate: string
  totalCost: string
}

export interface ServiceEstimateViewModel {
  serviceName: string
  currency: string
  parts: EstimatedPartViewModel[]
  labour: LabourEstimateViewModel
  estimatedDurationHours: number
  partsCost: string
  labourCost: string
  estimatedCost: string
}

export interface ComplaintSummaryViewModel {
  category: string
  description: string
  status: string
  evidence: string
  confidence: number | null
}

export interface PostCallSummaryViewModel {
  callId: string
  overallSummary: string
  languages: string[]
  sentiment: SentimentViewModel
  complaints: ComplaintSummaryViewModel[]
  unresolvedIssues: string[]
  actionsPromised: string[]
  followUpRequired: boolean
  customerSummary: string
  serviceEstimate: ServiceEstimateViewModel | null
}

export interface CallAnalysisViewModel {
  complaints: ComplaintViewModel[]
  sentiment: SentimentViewModel | null
  questionSuggestion: QuestionSuggestionViewModel | null
  serviceEstimate: ServiceEstimateViewModel | null
  postCallSummary: PostCallSummaryViewModel | null
  escalation: EscalationViewModel | null
}
