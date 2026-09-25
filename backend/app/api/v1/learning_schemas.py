from pydantic import BaseModel, ConfigDict

from app.domain.improvement_candidate import ImprovementReviewStatus, ImprovementType
from app.domain.learning_evidence import EvidenceType, LearningComponent


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