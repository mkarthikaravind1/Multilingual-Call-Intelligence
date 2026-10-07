from dataclasses import dataclass
from enum import Enum

from app.core.constants import COMPLAINT_CATEGORIES, SUPPORTED_LANGUAGES


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

        if self.target_category not in COMPLAINT_CATEGORIES:
            raise ValueError(
                f"Unsupported complaint category: {self.target_category!r}. "
                f"Must be one of {COMPLAINT_CATEGORIES}."
            )

        if not isinstance(self.priority, int) or self.priority < 0:
            raise ValueError("priority must be a non-negative integer.")

        if not isinstance(self.source, SuggestionSource):
            raise TypeError("source must be a SuggestionSource.")

        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0.")