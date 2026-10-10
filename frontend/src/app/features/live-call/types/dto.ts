import type {
  EscalationDto,
  EscalationLevel,
  EscalationStatus,
} from '../../escalation/types/dto'

export interface UtteranceRequestDto {
  utterance_id: string
  transcript: string
  speaker_role: string
  languages: string[]
  start_time: number
  end_time: number
  confidence?: number | null
}

export interface UtteranceDto extends UtteranceRequestDto {
  // The speaker's tone on this line (POSITIVE, NEUTRAL, NEGATIVE,
  // FRUSTRATED or ESCALATING); null until the analysis has rated it.
  sentiment?: string | null
  sentiment_confidence?: number | null
}

export interface CallSummaryDto {
  call_id: string
  status: string
  start_time: number
  end_time: number | null
  utterance_count: number
  // Present on call-list items; null when the call never escalated.
  escalation_level?: EscalationLevel | null
  escalation_status?: EscalationStatus | null
  // Present on call-list items; null until the caller / customer is known.
  // Name and registration are the CRM's, stored when the customer was identified.
  caller_number?: string | null
  customer_name?: string | null
  vehicle_registration?: string | null
  // Epoch seconds the last complaint was resolved; null while any is open
  // or when the call raised none.
  complaints_resolved_at?: number | null
  // Where the call was taken and by whom; null when not recorded. The
  // names are present on call-list items only.
  direction?: CallDirection | null
  location_id?: string | null
  location_name?: string | null
  executive_user_id?: string | null
  executive_name?: string | null
}

export type CallDirection = 'inbound' | 'outbound'

export interface CallDirectoryEntryDto {
  id: string
  name: string
  is_active: boolean
}

// What calls can be filtered by.
export interface CallDirectoryDto {
  locations: CallDirectoryEntryDto[]
  executives: CallDirectoryEntryDto[]
}

export interface CallResponseDto extends CallSummaryDto {
  utterances: UtteranceDto[]
}

export interface CallListResponseDto {
  items: CallSummaryDto[]
  total: number
  limit: number
  offset: number
}

export interface CallStatsResponseDto {
  total: number
  active: number
  completed: number
}

export interface ComplaintCoverageDto {
  call_id: string
  complaints: ComplaintDto[]
}

export interface ComplaintDto {
  category: string
  status: string
}

export interface SentimentDto {
  label: string
  confidence: number
  evidence: string
}

export interface QuestionSuggestionDto {
  question: string
  target_category: string
  priority: number
  reason: string
  source: string
  confidence: number | null
  // The question is in the customer's language; question_en is its
  // English version (null when the question is already English).
  language?: string
  question_en?: string | null
}

// Monetary fields are backend Decimals, serialized as JSON strings.
export interface EstimatedPartDto {
  name: string
  quantity: number
  // Before GST.
  unit_price: string
  total_price: string
  gst_percent: string
  gst_amount: string
}

export interface LabourEstimateDto {
  hours: number
  hourly_rate: string
  total_cost: string
  gst_percent: string
  gst_amount: string
}

export interface ServiceLineDto {
  service_name: string
  currency: string
  parts: EstimatedPartDto[]
  labour: LabourEstimateDto
  estimated_duration_hours: number
  parts_cost: string
  labour_cost: string
  // Before GST; total_cost = estimated_cost + gst_amount.
  estimated_cost: string
  gst_amount: string
  total_cost: string
  // The vehicle model this price is for; null: the all-models price.
  priced_for_model: string | null
  approximate: boolean
}

// Every service that came up in the call, and their totals.
export interface ServiceEstimateDto {
  currency: string
  services: ServiceLineDto[]
  estimated_duration_hours: number
  parts_cost: string
  labour_cost: string
  estimated_cost: string
  gst_amount: string
  total_cost: string
  vehicle_model: string | null
  approximate: boolean
}

export interface ComplaintSummaryDto {
  category: string
  description: string
  status: string
  evidence: string
  confidence: number | null
}

export interface PostCallSummaryDto {
  call_id: string
  overall_summary: string
  languages: string[]
  sentiment: SentimentDto
  complaints: ComplaintSummaryDto[]
  unresolved_issues: string[]
  actions_promised: string[]
  follow_up_required: boolean
  customer_summary: string
  service_estimate: ServiceEstimateDto | null
}

export interface CallAnalysisResponseDto {
  call_id: string
  coverage: ComplaintCoverageDto
  // null for a completed call whose post-call summary was never stored
  sentiment: SentimentDto | null
  question_suggestion: QuestionSuggestionDto | null
  service_estimate?: ServiceEstimateDto | null
  post_call_summary?: PostCallSummaryDto | null
  // null while the call has not escalated
  escalation?: EscalationDto | null
}

export interface CompleteCallRequestDto {
  // Left out: the server's clock.
  end_time?: number
}

export interface LiveTokenResponseDto {
  token: string
  expires_in: number
}

export interface LiveUtteranceMessageDto extends UtteranceRequestDto {
  type: 'utterance'
}

export interface LiveAnalysisEventDto extends CallAnalysisResponseDto {
  type: 'analysis'
  utterance_id: string
}

export type LiveErrorCode =
  | 'invalid_message'
  | 'invalid_utterance'
  | 'call_not_found'
  | 'internal_error'

export interface LiveErrorEventDto {
  type: 'error'
  code: LiveErrorCode | string
  call_id: string
  message: string
}

export type LiveServerEventDto = LiveAnalysisEventDto | LiveErrorEventDto
