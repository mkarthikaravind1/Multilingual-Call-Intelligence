from dataclasses import dataclass
import logging
from typing import Callable, Protocol

from app.ai.sentiment.provider import SentimentResult
from app.ai.summary.provider import PostCallSummaryRequest
from app.domain.conversation import Conversation, ConversationStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.customer_contact import CustomerContact
from app.domain.post_call_summary import PostCallSummary
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.service_estimate import ServiceEstimate
from app.domain.utterance import Utterance
from app.services.call_service import CallService
from app.services.conversation_analysis_service import (
    ConversationAnalysisResult,
    ConversationAnalysisService,
)
from app.services.conversation_coverage_repository import (
    ConversationCoverageRepository,
)
from app.services.conversation_service import ConversationCompletion
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryService
from app.services.estimation_service import EstimationService
from app.services.next_question_service import NextQuestionService
from app.services.post_call_summary_repository import (
    InMemoryPostCallSummaryRepository,
    PostCallSummaryRepository,
)
from app.services.post_call_summary_service import PostCallSummaryService

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class CallAnalysisResult:
    coverage: ConversationCoverage
    # None only for a completed call whose post-call summary was never stored.
    sentiment: SentimentResult | None
    question_suggestion: QuestionSuggestion | None
    service_estimate: ServiceEstimate | None
    post_call_summary: PostCallSummary | None = None

class LearningRecordingError(Exception):
    pass


class AnalysisLearningRecorder(Protocol):
    def record(self, call_id: str, result: CallAnalysisResult) -> None: ...

class CallWorkflowService:
    def __init__(
        self,
        call_service: CallService,
        coverage_repository: ConversationCoverageRepository,
        analysis_service: ConversationAnalysisService,
        next_question_service: NextQuestionService,
        estimation_service: EstimationService,
        post_call_summary_service: PostCallSummaryService,
        customer_summary_delivery_service: CustomerSummaryDeliveryService | None = None,
        customer_contact_resolver: Callable[[str], CustomerContact | None] | None = None,
        learning_recorder: AnalysisLearningRecorder | None = None,
        post_call_summary_repository: PostCallSummaryRepository | None = None,
        customer_summary_enabled: bool = False,
    ) -> None:
        self._call_service = call_service
        self._coverage_repository = coverage_repository
        self._analysis_service = analysis_service
        self._next_question_service = next_question_service
        self._estimation_service = estimation_service
        self._post_call_summary_service = post_call_summary_service
        self._customer_summary_delivery_service = customer_summary_delivery_service
        self._customer_contact_resolver = customer_contact_resolver
        self._learning_recorder = learning_recorder
        self._post_call_summary_repository = (
            post_call_summary_repository or InMemoryPostCallSummaryRepository()
        )
        self._customer_summary_enabled = customer_summary_enabled

    def process_utterance(
        self,
        call_id: str,
        utterance: Utterance,
    ) -> CallAnalysisResult:
        self._call_service.add_utterance(call_id, utterance)
        result = self.analyze_call(call_id)
        if self._learning_recorder is not None:
            try:
                self._learning_recorder.record(call_id, result)
            except LearningRecordingError:
                logger.exception("Learning recording failed for call %r", call_id)
        return result

    def analyze_call(self, call_id: str) -> CallAnalysisResult:
        conversation = self._call_service.get_call(call_id)

        if conversation.status == ConversationStatus.COMPLETED:
            return self._read_completed_analysis(conversation)

        analysis = self._analyze_and_save_coverage(conversation)
        suggestion = self._next_question_service.suggest_next_question(
            analysis.coverage,
            conversation.utterances,
        )

        return CallAnalysisResult(
            coverage=analysis.coverage,
            sentiment=analysis.sentiment,
            question_suggestion=suggestion,
            service_estimate=self._estimate_from_latest_utterance(
                conversation.latest_utterance
            ),
        )

    def complete_call(self, call_id: str, end_time: float) -> ConversationCompletion:
        """Shared completion entry point: post-call processing runs only
        when this request is the one that completed the call."""
        completion = self._call_service.end_call(call_id, end_time)
        if completion.completed_now:
            self.process_completed_call(call_id)
        return completion

    def process_completed_call(self, call_id: str) -> PostCallSummary | None:
        """Generate, store and deliver the post-call summary once.

        Safe to repeat: a stored summary is never regenerated. Failures are
        logged and leave the call COMPLETED.
        """
        conversation = self._call_service.get_call(call_id)
        if conversation.status != ConversationStatus.COMPLETED:
            logger.warning("Skipping post-call processing for active call %r", call_id)
            return None

        existing = self._post_call_summary_repository.get(call_id)
        if existing is not None:
            return existing

        if conversation.utterance_count == 0:
            # e.g. busy / no-answer: nothing was said, so there is nothing to summarise.
            logger.info("Skipping post-call summary for call %r without utterances", call_id)
            return None

        try:
            analysis = self._analyze_and_save_coverage(conversation)
            summary = self._post_call_summary_service.generate_summary(
                PostCallSummaryRequest(
                    call_id=conversation.call_id,
                    conversation=conversation,
                    complaint_coverages=analysis.coverage.complaints,
                    sentiment=analysis.sentiment,
                    service_estimate=self._estimate_from_latest_utterance(
                        conversation.latest_utterance
                    ),
                )
            )
        except Exception:
            logger.exception("Post-call summary generation failed for call %r", call_id)
            return None

        if summary is None:
            logger.warning("No post-call summary was produced for call %r", call_id)
            return None

        try:
            stored = self._post_call_summary_repository.add_if_absent(summary)
        except Exception:
            logger.exception("Storing the post-call summary failed for call %r", call_id)
            return None

        self._deliver_summary(stored)
        return stored

    def _analyze_and_save_coverage(
        self, conversation: Conversation
    ) -> ConversationAnalysisResult:
        coverage = self._coverage_repository.get(conversation.call_id)
        if coverage is None:
            coverage = ConversationCoverage(call_id=conversation.call_id)

        analysis = self._analysis_service.analyze(conversation, coverage)
        self._coverage_repository.save(analysis.coverage)
        return analysis

    def _read_completed_analysis(self, conversation: Conversation) -> CallAnalysisResult:
        # Read-only: no provider calls, no coverage writes, no learning usage,
        # no summary generation and no delivery.
        coverage = self._coverage_repository.get(conversation.call_id)
        if coverage is None:
            coverage = ConversationCoverage(call_id=conversation.call_id)

        summary = self._post_call_summary_repository.get(conversation.call_id)
        return CallAnalysisResult(
            coverage=coverage,
            sentiment=None if summary is None else summary.sentiment,
            question_suggestion=None,
            service_estimate=None if summary is None else summary.service_estimate,
            post_call_summary=summary,
        )

    def _deliver_summary(self, summary: PostCallSummary) -> None:
        if (
            not self._customer_summary_enabled
            or self._customer_summary_delivery_service is None
            or self._customer_contact_resolver is None
        ):
            return

        try:
            contact = self._customer_contact_resolver(summary.call_id)
            if contact is not None:
                self._customer_summary_delivery_service.send_summary_to_customer(
                    summary=summary,
                    contact=contact,
                )
        except Exception:
            logger.exception(
                "Customer summary delivery failed for call %r",
                summary.call_id,
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
