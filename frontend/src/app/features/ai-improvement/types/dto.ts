export type ImprovementType =
  | 'question_strategy'
  | 'complaint_detection'
  | 'sentiment_analysis'
  | 'estimation_rule'
  | 'general_process'

export type ImprovementReviewStatus =
  | 'pending_review'
  | 'approved'
  | 'rejected'

export type LearningComponent =
  | 'complaint_detection'
  | 'sentiment_analysis'
  | 'next_question'
  | 'estimation'
  | 'post_call_summary'
  | 'general'

// Every component, in the order the evidence filter lists them.
export const LEARNING_COMPONENTS: LearningComponent[] = [
  'next_question',
  'complaint_detection',
  'sentiment_analysis',
  'estimation',
  'post_call_summary',
  'general',
]

export type EvidenceType =
  | 'ai_prediction'
  | 'human_correction'
  | 'outcome'
  | 'question_feedback'

export interface LearningCandidateDto {
  candidate_id: string
  improvement_type: ImprovementType
  title: string
  description: string
  evidence: string[]
  occurrence_count: number
  confidence: number
  status: ImprovementReviewStatus
  created_at: number
  reviewed_at: number | null
}

export interface LearningPatternDto {
  pattern_id: string
  component: LearningComponent
  description: string
  occurrence_count: number
  evidence_ids: string[]
  suggested_improvement: string
  created_at: number
}

export type FeedbackType = 'human_correction' | 'question_effectiveness'

export type FeedbackSource = 'icr' | 'supervisor' | 'system'

export type QuestionOutcome = 'helpful' | 'not_helpful'

export interface LearningFeedbackDto {
  feedback_id: string
  observation_id: string
  call_id: string | null
  feedback_type: FeedbackType | 'outcome'
  corrected_value: string | null
  outcome: string | null
  original_value: string | null
  source: FeedbackSource
  notes: string | null
  created_at: number
}

export interface LearningFeedbackRequestDto {
  observation_id: string
  feedback_type: FeedbackType
  corrected_value?: string
  outcome?: QuestionOutcome
  notes?: string
}

// One AI output on a call that a person can confirm or correct.
export interface CallObservationDto {
  observation_id: string
  call_id: string
  component: LearningComponent
  predicted_value: string
  entity_id: string | null
  confidence: number
  created_at: number
  // Allowed corrections; empty means free text.
  correction_options: string[]
  feedback: LearningFeedbackDto | null
}

export type ActiveImprovementStatus = 'active' | 'inactive'

export type ImprovementEffectivenessStatus =
  | 'not_enough_evidence'
  | 'evidence_available'

export type ImprovementEffect = 'not_enough_data' | 'better' | 'no_change' | 'worse'

export interface ActiveImprovementDto {
  improvement_id: string
  candidate_id: string
  component: LearningComponent
  guidance: string
  proposed_behavior: string
  status: ActiveImprovementStatus
  activated_at: number
  deactivated_at: number | null
  usage_count: number
  feedback_count: number
  effectiveness_status: ImprovementEffectivenessStatus
  // Whether reviewers correct this output less often since it went live.
  effect: ImprovementEffect
  outputs_before: number
  corrections_before: number
  outputs_after: number
  corrections_after: number
}

export interface LearningEvidenceDto {
  evidence_id: string
  call_id: string
  evidence_type: EvidenceType
  component: LearningComponent
  description: string
  expected_value: string | null
  actual_value: string | null
  human_correction: string | null
  created_at: number
  // The call's customer as stored when identified; null until known.
  customer_name?: string | null
  vehicle_registration?: string | null
}