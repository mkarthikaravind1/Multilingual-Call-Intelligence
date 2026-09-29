from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.active_improvement import ActiveImprovementStatus
from app.domain.improvement_candidate import ImprovementReviewStatus, ImprovementType
from app.domain.improvement_effectiveness import ImprovementEffectivenessStatus
from app.domain.learning_evidence import EvidenceType, LearningComponent
from app.domain.learning_feedback import FeedbackSource, FeedbackType


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LearningCandidateResponse(_Response):
    candidate_id: str
    improvement_type: ImprovementType
    title: str
    description: str
    evidence: list[str]
    occurrence_count: int
    confidence: float
    status: ImprovementReviewStatus
    created_at: float
    reviewed_at: float | None


class LearningPatternResponse(_Response):
    pattern_id: str
    component: LearningComponent
    description: str
    occurrence_count: int
    evidence_ids: list[str]
    suggested_improvement: str
    created_at: float


class LearningEvidenceResponse(_Response):
    evidence_id: str
    call_id: str
    evidence_type: EvidenceType
    component: LearningComponent
    description: str
    expected_value: str | None
    actual_value: str | None
    human_correction: str | None
    created_at: float

class LearningFeedbackRequest(BaseModel):
    observation_id: str = Field(min_length=1)
    feedback_type: Literal[
        FeedbackType.HUMAN_CORRECTION, FeedbackType.QUESTION_EFFECTIVENESS
    ]
    corrected_value: str | None = None
    outcome: str | None = None
    notes: str | None = None


class LearningFeedbackResponse(_Response):
    feedback_id: str
    observation_id: str
    call_id: str | None
    feedback_type: FeedbackType
    corrected_value: str | None
    outcome: str | None
    original_value: str | None
    source: FeedbackSource
    notes: str | None
    created_at: float


class CallObservationResponse(BaseModel):
    observation_id: str
    call_id: str
    component: LearningComponent
    predicted_value: str
    entity_id: str | None
    confidence: float
    created_at: float
    # Allowed corrections for this output; empty means free text.
    correction_options: list[str]
    feedback: LearningFeedbackResponse | None


class ActiveImprovementResponse(BaseModel):
    improvement_id: str
    candidate_id: str
    component: LearningComponent
    # What reviewers corrected, as given to the AI at runtime.
    guidance: str
    proposed_behavior: str
    status: ActiveImprovementStatus
    activated_at: float
    deactivated_at: float | None
    usage_count: int
    feedback_count: int
    effectiveness_status: ImprovementEffectivenessStatus
