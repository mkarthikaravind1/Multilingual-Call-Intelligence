import type { CallDirection } from './dto'
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
  // The speaker's tone on this line; null until it is rated.
  sentiment: string | null
  // The complaint categories this line raises; several: multiCategory.
  complaintCategories: string[]
  multiCategory: boolean
}

export interface ComplaintViewModel {
  category: string
  status: string
  // 0 to 1; null when not recorded.
  confidence: number | null
}

export interface CallAlertViewModel {
  alertType: string
  subject: string
  message: string
  // null while the alert stands.
  clearedAt: number | null
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
  language: string
  questionEnglish: string | null
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
  direction: CallDirection | null
  locationId: string | null
  locationName: string | null
  executiveUserId: string | null
  executiveName: string | null
}

// Monetary values are kept as the backend's Decimal strings; never recalculated here.
export interface EstimatedPartViewModel {
  name: string
  quantity: number
  unitPrice: string
  totalPrice: string
  gstPercent: string
}

export interface LabourEstimateViewModel {
  hours: number
  hourlyRate: string
  totalCost: string
  gstPercent: string
}

export interface ServiceLineViewModel {
  serviceName: string
  currency: string
  parts: EstimatedPartViewModel[]
  labour: LabourEstimateViewModel
  estimatedDurationHours: number
  partsCost: string
  labourCost: string
  estimatedCost: string
  gstAmount: string
  totalCost: string
  pricedForModel: string | null
  approximate: boolean
}

export interface ServiceEstimateViewModel {
  currency: string
  services: ServiceLineViewModel[]
  estimatedDurationHours: number
  partsCost: string
  labourCost: string
  estimatedCost: string
  gstAmount: string
  totalCost: string
  vehicleModel: string | null
  approximate: boolean
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
  // Every suggested question, the most relevant first.
  questionSuggestions: QuestionSuggestionViewModel[]
  serviceEstimate: ServiceEstimateViewModel | null
  postCallSummary: PostCallSummaryViewModel | null
  escalation: EscalationViewModel | null
  alerts: CallAlertViewModel[]
}
