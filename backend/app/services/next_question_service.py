from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.utterance import Utterance
from app.domain.learning_evidence import LearningComponent     
from app.domain.runtime_improvement_context import RuntimeImprovementContext 
from app.services.runtime_improvement_service import RuntimeImprovementService

_ACTIONABLE_STATUSES = {
    ComplaintCoverageStatus.DETECTED,
    ComplaintCoverageStatus.PROBED,
}


class NextQuestionService:
    def __init__(
        self,
        provider: QuestionSuggestionProvider,
        runtime_improvement_service: RuntimeImprovementService | None = None,
    ) -> None:
        self._provider = provider
        self._runtime_improvement_service = runtime_improvement_service

    def suggest_next_question(
        self,
        coverage: ConversationCoverage,
        utterances: tuple[Utterance, ...] = (),
    ) -> QuestionSuggestion | None:
        complaint = self._select_candidate(coverage)
        if complaint is None:
            return None

        context = QuestionGenerationContext(
            category=complaint.category,
            status=complaint.status,
            utterances=utterances,
            learning_context=self._get_learning_context(),
        )
        return self._provider.generate(context)

    def _get_learning_context(self) -> tuple[RuntimeImprovementContext, ...]:
        if self._runtime_improvement_service is None:
            return ()
        return self._runtime_improvement_service.get_context_for_component(
            LearningComponent.NEXT_QUESTION
        )

    def _select_candidate(self, coverage: ConversationCoverage) -> ComplaintCoverage | None:
        for category in COMPLAINT_CATEGORIES:
            complaint = coverage.get(category)
            if complaint is not None and complaint.status in _ACTIONABLE_STATUSES:
                return complaint
        return None