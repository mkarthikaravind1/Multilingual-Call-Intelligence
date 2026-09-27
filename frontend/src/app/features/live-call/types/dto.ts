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

export interface CallResponseDto {
  call_id: string
  status: string
  start_time: number
  end_time: number | null
  utterance_count: number
  utterances: UtteranceDto[]
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

export interface CallAnalysisResponseDto {
  call_id: string
  coverage: ComplaintCoverageDto
  sentiment: SentimentDto
  question_suggestion: QuestionSuggestionDto | null
}

export interface CompleteCallRequestDto {
  end_time: number
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
