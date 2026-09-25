from dataclasses import dataclass
from enum import Enum


class FeedbackType(str, Enum):
    HUMAN_CORRECTION = "human_correction"
    OUTCOME = "outcome"
    QUESTION_EFFECTIVENESS = "question_effectiveness"


class FeedbackSource(str, Enum):
    ICR = "icr"
    SUPERVISOR = "supervisor"
    SYSTEM = "system"


@dataclass(frozen=True)
class LearningFeedback:
    feedback_id: str
    observation_id: str
    feedback_type: FeedbackType
    corrected_value: str | None
    outcome: str | None
    created_at: float
    call_id: str | None = None
    original_value: str | None = None
    source: FeedbackSource = FeedbackSource.ICR
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.feedback_id.strip():
            raise ValueError("feedback_id must not be empty.")

        if not self.observation_id.strip():
            raise ValueError("observation_id must not be empty.")

        if self.call_id is not None and (
            not isinstance(self.call_id, str) or not self.call_id.strip()
        ):
            raise ValueError("call_id must not be blank when provided.")

        if not isinstance(self.feedback_type, FeedbackType):
            raise ValueError("feedback_type must be a valid FeedbackType.")

        if not isinstance(self.source, FeedbackSource):
            raise ValueError("source must be a valid FeedbackSource.")

        if (
            self.corrected_value is not None
            and not self.corrected_value.strip()
        ):
            raise ValueError(
                "corrected_value must not be blank when provided."
            )

        if self.outcome is not None and not self.outcome.strip():
            raise ValueError("outcome must not be blank when provided.")

        if self.corrected_value is None and self.outcome is None:
            raise ValueError(
                "At least one of corrected_value or outcome must be provided."
            )

        if self.original_value is not None and not self.original_value.strip():
            raise ValueError("original_value must not be blank when provided.")

        if self.notes is not None and not self.notes.strip():
            raise ValueError("notes must not be blank when provided.")

        if not isinstance(self.created_at, (int, float)):
            raise ValueError("created_at must be numeric.")

        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")