from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.complaint_category import require_category_name
from app.domain.conversation import Conversation
from app.domain.runtime_improvement_context import RuntimeImprovementContext


@dataclass(frozen=True)
class ComplaintDetectionResult:
    category: str
    confidence: float
    evidence: str

    def __post_init__(self) -> None:
        # Which categories may be reported is checked by the provider
        # against the ComplaintCategoryCatalog.
        require_category_name(self.category)

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
    def detect(
        self,
        conversation: Conversation,
        learning_context: tuple[RuntimeImprovementContext, ...] = (),
    ) -> list[ComplaintDetectionResult]:
        """Return one result per complaint category found; an empty list means none.

        learning_context carries approved improvements for complaint detection;
        providers that cannot use it ignore it.
        """
        raise NotImplementedError