from dataclasses import dataclass

from app.domain.learning_evidence import LearningComponent


@dataclass(frozen=True)
class LearningObservation:
    observation_id: str
    call_id: str
    component: LearningComponent
    description: str
    predicted_value: str
    confidence: float
    created_at: float

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id must not be empty.")

        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")

        if not isinstance(self.component, LearningComponent):
            raise ValueError("component must be a valid LearningComponent.")

        if not self.description.strip():
            raise ValueError("description must not be empty.")

        if not self.predicted_value.strip():
            raise ValueError("predicted_value must not be empty.")

        if not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be numeric.")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")

        if not isinstance(self.created_at, (int, float)):
            raise ValueError("created_at must be numeric.")

        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")