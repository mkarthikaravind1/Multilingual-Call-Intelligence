from dataclasses import dataclass
from enum import Enum
from app.domain.learning_evidence import LearningComponent

class ImprovementType(str, Enum):
    QUESTION_STRATEGY = "question_strategy"
    COMPLAINT_DETECTION = "complaint_detection"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    ESTIMATION_RULE = "estimation_rule"
    GENERAL_PROCESS = "general_process"


class ImprovementReviewStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


def _require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_timestamp(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number, got {type(value).__name__}.")
    if value < 0:
        raise ValueError(f"{field_name} must not be negative.")

def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True)
class ImprovementSpecification:
    """Structured description of a proposed improvement. Data only — it
    describes WHAT might change, never HOW it is applied at runtime."""

    component: LearningComponent
    current_behavior: str
    proposed_behavior: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.component, LearningComponent):
            raise TypeError(
                f"component must be a LearningComponent, got {type(self.component).__name__}."
            )
        _require_text(self.current_behavior, "current_behavior")
        _require_text(self.proposed_behavior, "proposed_behavior")
        _require_text(self.reason, "reason")

@dataclass(frozen=True)
class ImprovementCandidate:
    """An AI-proposed improvement discovered from historical call data and
    human feedback. Provider-independent: no LLM/DB access, no self-
    modifying logic — this is a data record awaiting human review."""

    candidate_id: str
    improvement_type: ImprovementType
    title: str
    description: str
    evidence: tuple[str, ...]
    occurrence_count: int
    confidence: float
    status: ImprovementReviewStatus
    created_at: float
    reviewed_at: float | None = None
    specification: ImprovementSpecification | None = None

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, "candidate_id")

        if not isinstance(self.improvement_type, ImprovementType):
            raise TypeError(
                f"improvement_type must be an ImprovementType, got {type(self.improvement_type).__name__}."
            )

        _require_id(self.title, "title")
        _require_id(self.description, "description")

        if not isinstance(self.evidence, tuple):
            raise TypeError(f"evidence must be a tuple, got {type(self.evidence).__name__}.")
        if not self.evidence:
            raise ValueError("evidence must not be empty.")
        for item in self.evidence:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("evidence entries must be non-empty strings.")

        if isinstance(self.occurrence_count, bool) or not isinstance(self.occurrence_count, int):
            raise TypeError(
                f"occurrence_count must be an int, got {type(self.occurrence_count).__name__}."
            )
        if self.occurrence_count < 1:
            raise ValueError("occurrence_count must be at least 1.")

        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError(f"confidence must be a number, got {type(self.confidence).__name__}.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0.")

        if not isinstance(self.status, ImprovementReviewStatus):
            raise TypeError(
                f"status must be an ImprovementReviewStatus, got {type(self.status).__name__}."
            )

        _require_timestamp(self.created_at, "created_at")

        if self.reviewed_at is not None:
            _require_timestamp(self.reviewed_at, "reviewed_at")
            if self.reviewed_at < self.created_at:
                raise ValueError("reviewed_at cannot be before created_at.")

        if self.status is ImprovementReviewStatus.PENDING_REVIEW:
            if self.reviewed_at is not None:
                raise ValueError("PENDING_REVIEW candidates must not have reviewed_at set.")
        elif self.reviewed_at is None:
            raise ValueError(f"{self.status.value} candidates must have reviewed_at set.")

        if self.specification is not None and not isinstance(
            self.specification, ImprovementSpecification
        ):
            raise TypeError(
                f"specification must be an ImprovementSpecification or None, "
                f"got {type(self.specification).__name__}."
            )