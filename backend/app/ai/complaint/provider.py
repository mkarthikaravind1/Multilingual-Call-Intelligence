from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.conversation import Conversation


@dataclass(frozen=True)
class ComplaintDetectionResult:
    category: str
    confidence: float
    evidence: str

    def __post_init__(self) -> None:
        if self.category not in COMPLAINT_CATEGORIES:
            raise ValueError(
                f"Unsupported complaint category: {self.category!r}. "
                f"Must be one of {COMPLAINT_CATEGORIES}."
            )

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not (0.0 <= self.confidence <= 1.0)
        ):
            raise ValueError("confidence must be a number between 0.0 and 1.0.")

        if not self.evidence.strip():
            raise ValueError("evidence must not be empty.")


class ComplaintDetectionProvider(ABC):
    @abstractmethod
    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        """Return one result per complaint category found; an empty list means none."""
        raise NotImplementedError