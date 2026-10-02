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

export type UtteranceDto = UtteranceRequestDto

export interface CallSummaryDto {
  call_id: string
  status: string
  start_time: number
  end_time: number | null
  utterance_count: number
  // Present on call-list items; null when the call never escalated.
  escalation_level?: EscalationLevel | null
  escalation_status?: EscalationStatus | null
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
}

// Monetary fields are backend Decimals, serialized as JSON strings.
export interface EstimatedPartDto {
  name: string
  quantity: number
  unit_price: string
  total_price: string
}

export interface LabourEstimateDto {
  hours: number
  hourly_rate: string
  total_cost: string
}

export interface ServiceEstimateDto {
  service_name: string
  currency: string
  parts: EstimatedPartDto[]
  labour: LabourEstimateDto
  estimated_duration_hours: number
  parts_cost: string
  labour_cost: string
  estimated_cost: string
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
  end_time: number
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
