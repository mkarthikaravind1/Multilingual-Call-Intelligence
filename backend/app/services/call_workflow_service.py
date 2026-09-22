from dataclasses import dataclass

from app.ai.sentiment.provider import SentimentResult
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.service_estimate import ServiceEstimate
from app.domain.utterance import Utterance
from app.services.call_service import CallService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_coverage_repository import (
    ConversationCoverageRepository,
)
from app.services.estimation_service import EstimationService
from app.services.next_question_service import NextQuestionService


@dataclass(frozen=True)
class CallAnalysisResult:
    coverage: ConversationCoverage
    sentiment: SentimentResult
    question_suggestion: QuestionSuggestion | None
    service_estimate: ServiceEstimate | None


class CallWorkflowService:

    def __init__(
        self,
        call_service: CallService,
        coverage_repository: ConversationCoverageRepository,
        analysis_service: ConversationAnalysisService,
        next_question_service: NextQuestionService,
        estimation_service: EstimationService,
    ) -> None:
        self._call_service = call_service
        self._coverage_repository = coverage_repository
        self._analysis_service = analysis_service
        self._next_question_service = next_question_service
        self._estimation_service = estimation_service

    def process_utterance(
        self,
        call_id: str,
        utterance: Utterance,
    ) -> CallAnalysisResult:
        self._call_service.add_utterance(call_id, utterance)
        return self.analyze_call(call_id)

    def analyze_call(self, call_id: str) -> CallAnalysisResult:
        conversation = self._call_service.get_call(call_id)

        coverage = self._coverage_repository.get(call_id)

        if coverage is None:
            coverage = ConversationCoverage(call_id=call_id)

        analysis = self._analysis_service.analyze(
            conversation,
            coverage,
        )

        self._coverage_repository.save(analysis.coverage)

        suggestion = self._next_question_service.suggest_next_question(
            analysis.coverage,
            conversation.utterances,
        )

        service_estimate = self._estimate_from_latest_utterance(
            conversation.latest_utterance
        )

        return CallAnalysisResult(
            coverage=analysis.coverage,
            sentiment=analysis.sentiment,
            question_suggestion=suggestion,
            service_estimate=service_estimate,
        )

    def _estimate_from_latest_utterance(
        self,
        utterance: Utterance | None,
    ) -> ServiceEstimate | None:
        if utterance is None:
            return None

        return self._estimation_service.estimate(
            utterance.transcript
        )