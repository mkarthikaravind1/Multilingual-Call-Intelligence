from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.utterance import Utterance
from app.domain.runtime_improvement_context import RuntimeImprovementContext  

@dataclass(frozen=True)
class OpenComplaint:
    """A complaint raised on the call that may still need a question."""

    category: str
    status: ComplaintCoverageStatus
    # What counts as it, for categories with no built-in checklist
    # (accepted emerging themes).
    description: str | None = None


@dataclass
class QuestionGenerationContext:
    # The complaint the rule-based questions ask about (the first open one
    # in the fixed category order).
    category: str
    status: ComplaintCoverageStatus
    utterances: tuple[Utterance, ...]
    learning_context: tuple[RuntimeImprovementContext, ...] = ()
    # The customer's language: the question is written in it.
    language: str = "en"
    # Every open complaint; the LLM picks the most useful one to ask about.
    # Empty: ask about category.
    open_complaints: tuple[OpenComplaint, ...] = ()
    # The question suggested last time, so it is not suggested again.
    previous_question: str | None = None
    # Questions found to ask for something the customer already gave.
    answered_questions: tuple[str, ...] = ()
    # Questions the executive has already accepted or skipped on this call:
    # they are not suggested again.
    handled_questions: tuple[str, ...] = ()

class QuestionSuggestionProvider(ABC):
    @abstractmethod
    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        raise NotImplementedError

    def generate_ranked(
        self, context: QuestionGenerationContext, limit: int
    ) -> tuple[QuestionSuggestion, ...]:
        """Up to `limit` questions, the most relevant first. This default
        suits a provider that asks about one given complaint: one question
        per open complaint, in their order."""
        complaints = context.open_complaints or (
            OpenComplaint(context.category, context.status),
        )
        suggestions: list[QuestionSuggestion] = []
        for complaint in complaints:
            if len(suggestions) >= limit:
                break
            suggestion = self.generate(
                replace(context, category=complaint.category, status=complaint.status)
            )
            if suggestion is not None:
                suggestions.append(suggestion)
        return tuple(suggestions)