import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from app.ai.question.provider import (
    OpenComplaint,
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_coverage import (
    ComplaintCoverage,
    ComplaintCoverageStatus,
)
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.customer_language import customer_language
from app.domain.learning_evidence import LearningComponent
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.runtime_improvement_context import (
    RuntimeImprovementContext,
)
from app.domain.utterance import Utterance
from app.services.runtime_improvement_service import (
    RuntimeImprovementService,
)


# How many questions are suggested at a time, the most relevant first.
DEFAULT_QUESTION_LIMIT = 3

_ACTIONABLE_STATUSES = {
    ComplaintCoverageStatus.DETECTED,
    ComplaintCoverageStatus.PROBED,
}


class ImprovementUsageRecorder(Protocol):

    def record_runtime_usage(
        self,
        call_id: str,
        contexts: tuple[RuntimeImprovementContext, ...],
        suggestion: QuestionSuggestion,
    ) -> None:
        ...


class NextQuestionService:

    def __init__(
        self,
        provider: QuestionSuggestionProvider,
        runtime_improvement_service: RuntimeImprovementService | None = None,
        improvement_usage_recorder: ImprovementUsageRecorder | None = None,
        category_descriptions: Callable[[], Mapping[str, str | None]] | None = None,
        limit: int = DEFAULT_QUESTION_LIMIT,
        in_live_analysis: bool = True,
    ) -> None:
        self._provider = provider
        self._limit = max(1, limit)
        # Whether a combined live-analysis request may write the questions
        # too (see live_task), when the provider can take part in one.
        self._in_live_analysis = in_live_analysis
        # What counts as each accepted emerging theme (name -> description).
        self._category_descriptions = category_descriptions
        self._runtime_improvement_service = (
            runtime_improvement_service
        )
        self._improvement_usage_recorder = (
            improvement_usage_recorder
        )

    def suggest_next_question(
        self,
        coverage: ConversationCoverage,
        utterances: tuple[Utterance, ...] = (),
        previous_question: str | None = None,
    ) -> QuestionSuggestion | None:

        complaint = self._select_candidate(coverage)

        if complaint is None:
            return None

        learning_context = self._get_learning_context()

        context = QuestionGenerationContext(
            category=complaint.category,
            status=complaint.status,
            utterances=utterances,
            learning_context=learning_context,
            language=customer_language(utterances),
            open_complaints=self._open_complaints(coverage),
            previous_question=previous_question,
        )

        suggestion = self._provider.generate(context)

        self._record_learning_usage(
            coverage.call_id,
            learning_context,
            suggestion,
        )

        return suggestion

    # ---- Several questions, the most relevant first ----

    def suggest_questions(
        self,
        coverage: ConversationCoverage,
        utterances: tuple[Utterance, ...] = (),
        handled_questions: tuple[str, ...] = (),
    ) -> tuple[QuestionSuggestion, ...]:
        """Up to the limit of questions about the call's open complaints,
        the most relevant first, with a request of their own.
        handled_questions: those the executive has already accepted or
        skipped on this call, which are not suggested again."""
        context = self._context(coverage, utterances, handled_questions)
        if context is None:
            return ()
        suggestions = self._not_handled(
            self._provider.generate_ranked(context, self._limit), handled_questions
        )
        self._record_ranked_usage(coverage.call_id, context, suggestions)
        return suggestions

    def live_task(
        self, utterances: tuple[Utterance, ...], handled_questions: tuple[str, ...] = ()
    ) -> str | None:
        """The questions' task for a combined live-analysis request, so the
        same request that finds the complaints also writes the questions
        (no request of their own, and no wait for one). None when the
        provider cannot take part in one, or this is turned off."""
        ranked_task = getattr(self._provider, "ranked_task", None)
        if not self._in_live_analysis or ranked_task is None:
            return None
        # Which complaints are open is not known yet: the task names none.
        context = QuestionGenerationContext(
            category=COMPLAINT_CATEGORIES[0],
            status=ComplaintCoverageStatus.DETECTED,
            utterances=utterances,
            learning_context=self._get_learning_context(),
            language=customer_language(utterances),
            handled_questions=handled_questions,
        )
        return ranked_task(context, self._limit)

    def drafted_questions(
        self,
        coverage: ConversationCoverage,
        utterances: tuple[Utterance, ...],
        answer,
        handled_questions: tuple[str, ...] = (),
    ) -> tuple[QuestionSuggestion, ...] | None:
        """The questions a combined live-analysis request wrote (answer:
        its decoded "questions"), against the coverage that request left.
        Not yet checked against what the customer has said: see
        checked(). None when the answer cannot be used, and the questions
        are to be asked for on their own."""
        parse_ranked = getattr(self._provider, "parse_ranked", None)
        if answer is None or parse_ranked is None:
            return None
        context = self._context(coverage, utterances, handled_questions)
        if context is None:
            return ()
        suggestions = parse_ranked(answer, context, self._limit)
        return None if suggestions is None else self._not_handled(suggestions, handled_questions)

    def checked(
        self,
        coverage: ConversationCoverage,
        utterances: tuple[Utterance, ...],
        drafted: tuple[QuestionSuggestion, ...],
    ) -> tuple[QuestionSuggestion, ...]:
        """The drafted questions without those the customer has already
        answered (one request for all of them)."""
        context = self._context(coverage, utterances)
        check = getattr(self._provider, "checked", None)
        if context is None or check is None or not drafted:
            return drafted
        suggestions = check(drafted, context)
        self._record_ranked_usage(coverage.call_id, context, suggestions)
        return suggestions

    def _context(
        self,
        coverage: ConversationCoverage,
        utterances: tuple[Utterance, ...],
        handled_questions: tuple[str, ...] = (),
    ) -> QuestionGenerationContext | None:
        """What a provider is given to write questions; None when the call
        has no open complaint to ask about."""
        complaint = self._select_candidate(coverage)
        if complaint is None:
            return None
        return QuestionGenerationContext(
            category=complaint.category,
            status=complaint.status,
            utterances=utterances,
            learning_context=self._get_learning_context(),
            language=customer_language(utterances),
            open_complaints=self._open_complaints(coverage),
            handled_questions=handled_questions,
        )

    @staticmethod
    def _not_handled(
        suggestions: tuple[QuestionSuggestion, ...], handled_questions: tuple[str, ...]
    ) -> tuple[QuestionSuggestion, ...]:
        handled = {text.casefold() for text in handled_questions}
        return tuple(
            s
            for s in suggestions
            if s.question.casefold() not in handled
            and (s.question_en or "").casefold() not in handled
        )

    def _record_ranked_usage(
        self,
        call_id: str,
        context: QuestionGenerationContext,
        suggestions: tuple[QuestionSuggestion, ...],
    ) -> None:
        # The guidance shaped the whole list; it is recorded with its first.
        self._record_learning_usage(
            call_id, context.learning_context, suggestions[0] if suggestions else None
        )

    def _get_learning_context(
        self,
    ) -> tuple[RuntimeImprovementContext, ...]:

        if self._runtime_improvement_service is None:
            return ()

        return self._runtime_improvement_service.get_context_for_component(
            LearningComponent.NEXT_QUESTION
        )

    def _record_learning_usage(
        self,
        call_id: str,
        contexts: tuple[RuntimeImprovementContext, ...],
        suggestion: QuestionSuggestion | None,
    ) -> None:

        if (
            self._improvement_usage_recorder is None
            or not contexts
            or suggestion is None
        ):
            return

        try:
            self._improvement_usage_recorder.record_runtime_usage(
                call_id,
                contexts,
                suggestion,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to record learning improvement usage. "
                "Continuing normal next-question processing."
            )

    def _open_complaints(self, coverage: ConversationCoverage) -> tuple[OpenComplaint, ...]:
        """The actionable complaints, built-ins in their fixed order first."""
        descriptions: Mapping[str, str | None] = {}
        if self._category_descriptions is not None:
            try:
                descriptions = self._category_descriptions()
            except Exception:
                logging.getLogger(__name__).exception("Could not read the category descriptions")
        open_ = [c for c in coverage.complaints if c.status in _ACTIONABLE_STATUSES]
        order = {category: index for index, category in enumerate(COMPLAINT_CATEGORIES)}
        open_.sort(key=lambda c: order.get(c.category, len(order)))
        return tuple(
            OpenComplaint(c.category, c.status, descriptions.get(c.category)) for c in open_
        )

    def _select_candidate(
        self,
        coverage: ConversationCoverage,
    ) -> ComplaintCoverage | None:

        # Built-in categories in their fixed order, then any others
        # (accepted emerging themes) in the order they were raised.
        for category in COMPLAINT_CATEGORIES:
            complaint = coverage.get(category)

            if (
                complaint is not None
                and complaint.status in _ACTIONABLE_STATUSES
            ):
                return complaint

        for complaint in coverage.complaints:
            if (
                complaint.category not in COMPLAINT_CATEGORIES
                and complaint.status in _ACTIONABLE_STATUSES
            ):
                return complaint

        return None