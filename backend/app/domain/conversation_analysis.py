from dataclasses import dataclass
from enum import Enum

from app.core.constants import SUPPORTED_LANGUAGES
from app.domain.complaint_category import require_category_name


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass(frozen=True)
class ComplaintDetection:
    category: str
    confidence: float

    def __post_init__(self) -> None:
        require_category_name(self.category)

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")


@dataclass(frozen=True)
class ConversationAnalysis:
    utterance_id: str
    detected_languages: tuple[str, ...]
    complaints: tuple[ComplaintDetection, ...] = ()
    sentiment: Sentiment | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.utterance_id.strip():
            raise ValueError("utterance_id must not be empty.")

        if not self.detected_languages:
            raise ValueError(
                "At least one detected language is required."
            )

        for language in self.detected_languages:
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError(
                    f"Unsupported language code: {language!r}."
                )

        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")