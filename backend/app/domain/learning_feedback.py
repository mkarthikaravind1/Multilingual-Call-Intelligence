from dataclasses import dataclass
from enum import Enum


class FeedbackType(str, Enum):
    HUMAN_CORRECTION = "human_correction"
    OUTCOME = "outcome"
    QUESTION_EFFECTIVENESS = "question_effectiveness"


@dataclass(frozen=True)
class LearningFeedback:
    feedback_id: str
    observation_id: str
    feedback_type: FeedbackType
    corrected_value: str | None
    outcome: str | None
    created_at: float

    def __post_init__(self) -> None:
        if not self.feedback_id.strip():
            raise ValueError("feedback_id must not be empty.")

        if not self.observation_id.strip():
            raise ValueError("observation_id must not be empty.")

        if not isinstance(self.feedback_type, FeedbackType):
            raise ValueError("feedback_type must be a valid FeedbackType.")

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

        if not isinstance(self.created_at, (int, float)):
            raise ValueError("created_at must be numeric.")

        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")