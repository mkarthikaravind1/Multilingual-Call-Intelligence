from dataclasses import dataclass
from enum import Enum


class EvidenceType(str, Enum):
    AI_PREDICTION = "ai_prediction"
    HUMAN_CORRECTION = "human_correction"
    OUTCOME = "outcome"
    QUESTION_FEEDBACK = "question_feedback"


class LearningComponent(str, Enum):
    COMPLAINT_DETECTION = "complaint_detection"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    NEXT_QUESTION = "next_question"
    ESTIMATION = "estimation"
    POST_CALL_SUMMARY = "post_call_summary"
    GENERAL = "general"


@dataclass(frozen=True)
class LearningEvidence:
    evidence_id: str
    call_id: str
    evidence_type: EvidenceType
    component: LearningComponent
    description: str
    expected_value: str | None
    actual_value: str | None
    human_correction: str | None
    created_at: float

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must not be empty.")

        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")

        if not isinstance(self.evidence_type, EvidenceType):
            raise ValueError("evidence_type must be a valid EvidenceType.")

        if not isinstance(self.component, LearningComponent):
            raise ValueError("component must be a valid LearningComponent.")

        if not self.description.strip():
            raise ValueError("description must not be empty.")

        if self.expected_value is not None and not self.expected_value.strip():
            raise ValueError("expected_value must not be blank when provided.")

        if self.actual_value is not None and not self.actual_value.strip():
            raise ValueError("actual_value must not be blank when provided.")

        if (
            self.human_correction is not None
            and not self.human_correction.strip()
        ):
            raise ValueError(
                "human_correction must not be blank when provided."
            )

        if not isinstance(self.created_at, (int, float)):
            raise ValueError("created_at must be numeric.")

        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")