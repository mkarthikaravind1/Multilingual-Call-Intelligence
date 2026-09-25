from dataclasses import dataclass

from app.domain.learning_evidence import LearningComponent


@dataclass(frozen=True)
class ImprovementUsage:
    usage_id: str
    improvement_id: str
    candidate_id: str
    call_id: str
    component: LearningComponent
    output_value: str
    used_at: float

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.usage_id, "usage_id"),
            (self.improvement_id, "improvement_id"),
            (self.candidate_id, "candidate_id"),
            (self.call_id, "call_id"),
            (self.output_value, "output_value"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be empty.")

        if not isinstance(self.component, LearningComponent):
            raise TypeError(
                "component must be a valid LearningComponent."
            )

        if isinstance(self.used_at, bool) or not isinstance(
            self.used_at, (int, float)
        ):
            raise TypeError("used_at must be numeric.")

        if self.used_at < 0:
            raise ValueError("used_at must not be negative.")