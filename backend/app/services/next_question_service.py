from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.utterance import Utterance

_ACTIONABLE_STATUSES = {
    ComplaintCoverageStatus.DETECTED,
    ComplaintCoverageStatus.PROBED,
}


class NextQuestionService:
    def __init__(self, provider: QuestionSuggestionProvider) -> None:
        self._provider = provider

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
        )
        return self._provider.generate(context)

    def _select_candidate(self, coverage: ConversationCoverage) -> ComplaintCoverage | None:
        for category in COMPLAINT_CATEGORIES:
            complaint = coverage.get(category)
            if complaint is not None and complaint.status in _ACTIONABLE_STATUSES:
                return complaint
        return None