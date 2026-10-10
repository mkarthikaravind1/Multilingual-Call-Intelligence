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
    # Whether the ICR has asked the customer about this complaint yet.
    probed: bool = False
    # The numbers of the call's lines that raise it (1 is the first line),
    # when the provider says; empty when it does not.
    lines: tuple[int, ...] = ()

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


@dataclass(frozen=True)
class UtteranceCategories:
    """The complaint categories one line of the call raises."""

    utterance_id: str
    # In the order the complaints were reported; empty: none.
    categories: tuple[str, ...]
    # The line as it was when analysed: a line that has changed since (live
    # speech continued it) is analysed again rather than given these.
    transcript: str


def line_categories(
    conversation: Conversation, detections
) -> tuple[UtteranceCategories, ...] | None:
    """What each line of the conversation raises, by these detections of
    it: every line, so one no longer named loses its categories. None when
    the detections name no line at all (a provider that does not say, or an
    answer that could not be used): the lines then keep what they have."""
    utterances = conversation.utterances
    raised: dict[int, list[str]] = {}
    for detection in detections:
        for number in getattr(detection, "lines", ()):
            if 1 <= number <= len(utterances) and detection.category not in raised.setdefault(
                number, []
            ):
                raised[number].append(detection.category)
    if not raised:
        return None
    return tuple(
        UtteranceCategories(
            utterance_id=utterance.utterance_id,
            categories=tuple(raised.get(number, ())),
            transcript=utterance.transcript,
        )
        for number, utterance in enumerate(utterances, start=1)
    )


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