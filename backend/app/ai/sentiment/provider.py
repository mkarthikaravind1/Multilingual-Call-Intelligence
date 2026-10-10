from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.conversation import Conversation
from app.domain.runtime_improvement_context import RuntimeImprovementContext
from app.domain.sentiment import SentimentLabel


@dataclass(frozen=True)
class UtteranceSentiment:
    """The tone of one line of the call."""

    utterance_id: str
    label: SentimentLabel
    confidence: float
    # The line as it was when rated: a line that has changed since (live
    # speech continued it) is rated again rather than given this tone.
    transcript: str

    def __post_init__(self) -> None:
        if not isinstance(self.label, SentimentLabel):
            raise TypeError(f"label must be a SentimentLabel, got {type(self.label).__name__}.")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError(
                f"confidence must be a number, got {type(self.confidence).__name__}."
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0.")


@dataclass(frozen=True)
class SentimentResult:
    label: SentimentLabel
    confidence: float
    evidence: str
    # The tone of individual lines, when the provider rated any.
    lines: tuple[UtteranceSentiment, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.label, SentimentLabel):
            raise TypeError(
                f"label must be a SentimentLabel, got {type(self.label).__name__}."
            )

        # bool is a subclass of int, so it must be rejected explicitly.
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise TypeError(
                f"confidence must be a number, got {type(self.confidence).__name__}."
            )

        # Written as a positive range check so NaN is rejected too.
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0.")

        if not isinstance(self.evidence, str):
            raise TypeError(
                f"evidence must be a string, got {type(self.evidence).__name__}."
            )

        if not self.evidence.strip():
            raise ValueError("evidence must not be empty.")


class SentimentAnalysisProvider(ABC):
    @abstractmethod
    def analyze(
        self,
        conversation: Conversation,
        learning_context: tuple[RuntimeImprovementContext, ...] = (),
    ) -> SentimentResult:
        """learning_context carries approved improvements for sentiment
        analysis; providers that cannot use it ignore it."""
        raise NotImplementedError