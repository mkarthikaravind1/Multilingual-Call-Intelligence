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
    ) -> None:
        self._provider = provider
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