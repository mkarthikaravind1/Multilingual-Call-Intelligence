from dataclasses import dataclass

from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.next_question_service import NextQuestionService


@dataclass(frozen=True)
class ConversationAnalysisResult:
    coverage: ConversationCoverage
    question_suggestion: QuestionSuggestion | None


class ConversationAnalysisService:
    def __init__(
        self,
        complaint_analysis: ComplaintAnalysisService,
        next_question: NextQuestionService,
    ) -> None:
        self._complaint_analysis = complaint_analysis
        self._next_question = next_question

    def analyze(
        self, conversation: Conversation, coverage: ConversationCoverage
    ) -> ConversationAnalysisResult:
        updated_coverage = self._complaint_analysis.analyze(conversation, coverage)
        suggestion = self._next_question.suggest_next_question(
            updated_coverage, conversation.utterances
        )
        return ConversationAnalysisResult(
            coverage=updated_coverage, question_suggestion=suggestion
        )