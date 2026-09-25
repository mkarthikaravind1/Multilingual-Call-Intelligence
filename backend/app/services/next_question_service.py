import logging
from typing import Protocol

from app.ai.question.provider import (
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_coverage import (
    ComplaintCoverage,
    ComplaintCoverageStatus,
)
from app.domain.conversation_coverage import ConversationCoverage
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
    ) -> None:
        self._provider = provider
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

    def _select_candidate(
        self,
        coverage: ConversationCoverage,
    ) -> ComplaintCoverage | None:

        for category in COMPLAINT_CATEGORIES:
            complaint = coverage.get(category)

            if (
                complaint is not None
                and complaint.status in _ACTIONABLE_STATUSES
            ):
                return complaint

        return None