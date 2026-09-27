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
}