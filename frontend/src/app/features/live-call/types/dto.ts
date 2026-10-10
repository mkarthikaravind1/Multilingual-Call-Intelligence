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
  // The complaint categories this line raises, once the analysis has
  // found them; multi_category: it covers more than one.
  complaint_categories?: string[]
  multi_category?: boolean
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
  // How sure the detector was (0 to 1); null when not recorded.
  confidence?: number | null
}

// An on-screen alert on a call: uncovered_category, high_severity_category,
// low_confidence or poor_audio.
export interface CallAlertDto {
  alert_type: string
  // The complaint category it is about; "" for the call itself.
  subject: string
  message: string
  raised_at: number
  // null while the alert stands.
  cleared_at: number | null
}

// A call's stored recording (supervisors and admins).
export interface CallRecordingDto {
  // Whether this server keeps call recordings at all.
  enabled: boolean
  // Whether this call has one that can be listened to now.
  available: boolean
  duration_seconds: number | null
  size_bytes: number | null
  // 2: the caller on the left, the other party on the right.
  channels: number | null
  created_at: number | null
  // When it is (or was) due to be removed.
  delete_after: number | null
  deleted_at: number | null
  // How many times it has been listened to.
  plays: number
}

export type QuestionOutcomeChoice = 'accepted' | 'skipped'

export interface QuestionOutcomeDto {
  question: string
  target_category: string
  outcome: QuestionOutcomeChoice
  created_at: number
}

// An active call, as the supervisor's live view shows it.
export interface LiveCallDto {
  call_id: string
  start_time: number
  direction: CallDirection | null
  location_name: string | null
  executive_name: string | null
  caller_number: string | null
  customer_name: string | null
  utterance_count: number
  // The customer's tone at the latest analysis; null before the first.
  sentiment: string | null
  complaints: ComplaintDto[]
  escalation_level: EscalationLevel | null
  escalation_status: EscalationStatus | null
  // Standing alerts only.
  alerts: CallAlertDto[]
}

export interface LiveCallsDto {
  // One page of the calls matching the filters, most urgent first.
  items: LiveCallDto[]
  limit: number
  offset: number
  // Calls matching the filters, across all pages.
  matching: number
  // Over every call in progress, whatever the filters:
  total: number
  with_alerts: number
  negative_tone: number
  escalated: number
  // The server's clock (epoch seconds).
  now: number
}

// Every filter is optional.
export interface LiveCallsFilters {
  locationId?: string
  executiveUserId?: string
  // A tone label, e.g. FRUSTRATED.
  sentiment?: string
  alertsOnly?: boolean
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
  // The most relevant suggested question (the first of
  // question_suggestions).
  question_suggestion: QuestionSuggestionDto | null
  // Every suggested question, the most relevant first.
  question_suggestions?: QuestionSuggestionDto[]
  service_estimate?: ServiceEstimateDto | null
  post_call_summary?: PostCallSummaryDto | null
  // null while the call has not escalated
  escalation?: EscalationDto | null
  // Standing and cleared, oldest first.
  alerts?: CallAlertDto[]
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
