from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from app.domain.conversation import Conversation


class SentimentLabel(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


@dataclass(frozen=True)
class SentimentResult:
    label: SentimentLabel
    confidence: float
    evidence: str

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
    def analyze(self, conversation: Conversation) -> SentimentResult:
        raise NotImplementedError