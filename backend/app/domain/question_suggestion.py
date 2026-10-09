from dataclasses import dataclass
from enum import Enum

from app.core.constants import SUPPORTED_LANGUAGES
from app.domain.complaint_category import require_category_name


class SuggestionSource(str, Enum):
    RULE_BASED = "rule_based"
    LLM = "llm"
    ML_MODEL = "ml_model"
    MANUAL = "manual"


@dataclass(frozen=True)
class QuestionSuggestion:
    question: str
    target_category: str
    priority: int
    reason: str
    source: SuggestionSource
    confidence: float | None = None
    # The language the question is written in (the customer's), and its
    # English version for the ICR when that is another language.
    language: str = "en"
    question_en: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty.")

        if self.language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported question language: {self.language!r}.")

        if self.question_en is not None and not self.question_en.strip():
            raise ValueError("question_en must not be empty when given.")

        if not self.reason.strip():
            raise ValueError("reason must not be empty.")

        require_category_name(self.target_category)

        if not isinstance(self.priority, int) or self.priority < 0:
            raise ValueError("priority must be a non-negative integer.")

        if not isinstance(self.source, SuggestionSource):
            raise TypeError("source must be a SuggestionSource.")

        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0.")