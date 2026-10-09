from dataclasses import dataclass, replace
import logging
from typing import Callable, Protocol

from app.ai.sentiment.provider import SentimentResult
from app.ai.summary.provider import PostCallSummaryRequest
from app.domain.conversation import Conversation, ConversationStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.customer_contact import CustomerContact
from app.domain.escalation import Escalation
from app.domain.post_call_summary import PostCallSummary
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.service_estimate import CallServiceEstimate
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
from app.services.complaint_lifecycle_service import ComplaintLifecycleService
from app.services.emerging_complaint_service import EmergingComplaintService
from app.services.escalation_service import EscalationService
from app.services.estimation_service import EstimationService
from app.services.live_analysis_store import (
    DEFAULT_LIVE_ANALYSIS_TTL_SECONDS,
    LiveAnalysisSnapshot,
    LiveAnalysisStore,
)
from app.services.live_state_store import InMemoryLiveStateStore, LiveStateStore
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
    service_estimate: CallServiceEstimate | None
    post_call_summary: PostCallSummary | None = None
    # None when the call has never escalated (or escalation is not wired).
    escalation: Escalation | None = None

class LearningRecordingError(Exception):
    pass


class _CallCompletedDuringAnalysis(Exception):
    """A deferred analysis finished after the call completed; its results
    must not overwrite the final (post-call) analysis."""


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
        escalation_service: EscalationService | None = None,
        complaint_lifecycle_service: ComplaintLifecycleService | None = None,
        customer_id_resolver: Callable[[str], str | None] | None = None,
        emerging_complaint_service: EmergingComplaintService | None = None,
        emerging_complaint_auto_discovery: bool = False,
        live_state_store: LiveStateStore | None = None,
        live_analysis_ttl_seconds: float = DEFAULT_LIVE_ANALYSIS_TTL_SECONDS,
        transcript_reviser: Callable[[Conversation], tuple[Utterance, ...] | None]
        | None = None,
        vehicle_model_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        # The model of the caller's vehicle (from the CRM), so the estimate
        # uses that model's prices; None when it is not known.
        self._vehicle_model_resolver = vehicle_model_resolver
        # After the call: a better transcript of the whole call (e.g. from
        # its recording, see PostCallRetranscriptionService), or None.
        self._transcript_reviser = transcript_reviser
        self._escalation_service = escalation_service
        self._complaint_lifecycle_service = complaint_lifecycle_service
        self._customer_id_resolver = customer_id_resolver
        self._emerging_complaint_service = emerging_complaint_service
        self._emerging_complaint_auto_discovery = emerging_complaint_auto_discovery
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
        # The analysis of each active call's latest speech. Reads of an
        # active call return it rather than re-running the AI providers, so
        # polling a call costs no LLM calls. Kept in the live state store
        # (Redis when several instances run) so every instance sees it;
        # dropped on completion.
        self._live_analysis = LiveAnalysisStore(
            live_state_store or InMemoryLiveStateStore(), live_analysis_ttl_seconds
        )

    def process_utterance(
        self,
        call_id: str,
        utterance: Utterance,
    ) -> CallAnalysisResult:
        """Store the utterance and analyse the call, in one step."""
        self.record_utterance(call_id, utterance)
        conversation = self._call_service.get_call(call_id)
        if conversation.status == ConversationStatus.COMPLETED:
            result = self._read_completed_analysis(conversation)
        else:
            result = self._analyze_and_store(conversation)
        self._record_learning(call_id, result)
        return result

    def process_utterance_update(
        self,
        call_id: str,
        utterance: Utterance,
    ) -> CallAnalysisResult:
        """Update the latest utterance and analyse the call, in one step."""
        self.record_utterance_update(call_id, utterance)
        conversation = self._call_service.get_call(call_id)
        result = self._analyze_and_store(conversation)
        self._record_learning(call_id, result)
        return result

    def record_utterance(self, call_id: str, utterance: Utterance) -> None:
        """Store the utterance and let open live views show it at once,
        before (and independently of) the slower AI analysis."""
        self._call_service.add_utterance(call_id, utterance)
        self._live_analysis.touch(call_id)

    def record_utterance_update(self, call_id: str, utterance: Utterance) -> None:
        """Like record_utterance, for the call's latest utterance growing
        (same utterance_id) as live speech continues it."""
        self._call_service.update_latest_utterance(call_id, utterance)
        self._live_analysis.touch(call_id)

    def analyze_latest_speech(self, call_id: str) -> CallAnalysisResult | None:
        """Run the AI analysis over the call as it is now (all utterances
        recorded so far). None when the call has completed: its post-call
        processing makes the final analysis."""
        conversation = self._call_service.get_call(call_id)
        if conversation.status == ConversationStatus.COMPLETED:
            return None
        try:
            result = self._analyze_and_store(
                conversation, still_active=lambda: self._is_active(call_id)
            )
        except _CallCompletedDuringAnalysis:
            logger.info("Discarding live analysis of call %r: it completed meanwhile", call_id)
            return None
        except Exception:
            # e.g. the LLM is rate limited: the estimate does not depend on
            # the rest of the analysis, so it is still brought up to date.
            self._refresh_live_estimate(conversation)
            raise
        self._record_learning(call_id, result)
        return result

    def _refresh_live_estimate(self, conversation: Conversation) -> None:
        estimate = self._estimate_call(conversation)
        previous = self._live_analysis.load(conversation.call_id)
        if estimate is None or (previous is not None and previous.service_estimate == estimate):
            return
        self._live_analysis.save(
            conversation.call_id,
            LiveAnalysisSnapshot(
                sentiment=None if previous is None else previous.sentiment,
                question_suggestion=None if previous is None else previous.question_suggestion,
                service_estimate=estimate,
            ),
        )

    def _is_active(self, call_id: str) -> bool:
        return self._call_service.get_call(call_id).status != ConversationStatus.COMPLETED

    def _analyze_and_store(
        self,
        conversation: Conversation,
        still_active: Callable[[], bool] | None = None,
    ) -> CallAnalysisResult:
        call_id = conversation.call_id
        result = self._analyze_active_call(conversation, still_active)
        self._track_complaints(result.coverage)
        # Escalation is assessed only on new speech; reads reuse the result.
        if self._escalation_service is not None:
            result = replace(
                result,
                escalation=self._escalation_service.assess(
                    conversation, result.coverage, result.sentiment
                ),
            )
        self._live_analysis.save(
            call_id,
            LiveAnalysisSnapshot(
                sentiment=result.sentiment,
                question_suggestion=result.question_suggestion,
                service_estimate=result.service_estimate,
            ),
        )
        return result

    def _record_learning(self, call_id: str, result: CallAnalysisResult) -> None:
        if self._learning_recorder is None:
            return
        try:
            self._learning_recorder.record(call_id, result)
        except LearningRecordingError:
            logger.exception("Learning recording failed for call %r", call_id)

    def analyze_call(self, call_id: str) -> CallAnalysisResult:
        conversation = self._call_service.get_call(call_id)

        if conversation.status == ConversationStatus.COMPLETED:
            self._forget_live_result(call_id)
            return self._read_completed_analysis(conversation)
        return self._read_active_analysis(conversation)

    def _read_active_analysis(self, conversation: Conversation) -> CallAnalysisResult:
        # Read-only, like _read_completed_analysis: the providers run only
        # when new speech arrives (process_utterance).
        call_id = conversation.call_id
        latest = self._live_analysis.load(call_id)
        # Stored coverage is the source of truth: it also reflects complaint
        # updates made outside the live analysis.
        coverage = self._coverage_repository.get(call_id)
        return CallAnalysisResult(
            coverage=coverage or ConversationCoverage(call_id=call_id),
            sentiment=None if latest is None else latest.sentiment,
            question_suggestion=None if latest is None else latest.question_suggestion,
            service_estimate=None if latest is None else latest.service_estimate,
            escalation=self._stored_escalation(call_id),
        )

    def live_revision(self, call_id: str) -> str | None:
        """Changes whenever the call's live analysis changes or the call
        completes; None when nothing has happened yet (or it expired)."""
        return self._live_analysis.revision(call_id)

    def _forget_live_result(self, call_id: str) -> None:
        self._live_analysis.forget(call_id)

    def _analyze_active_call(
        self,
        conversation: Conversation,
        still_active: Callable[[], bool] | None = None,
    ) -> CallAnalysisResult:
        analysis = self._analyze_and_save_coverage(conversation, still_active)
        suggestion = self._next_question_service.suggest_next_question(
            analysis.coverage,
            conversation.utterances,
        )

        return CallAnalysisResult(
            coverage=analysis.coverage,
            sentiment=analysis.sentiment,
            question_suggestion=suggestion,
            service_estimate=self._estimate_call(conversation),
        )

    def _assess_final_escalation(
        self, conversation: Conversation, analysis: ConversationAnalysisResult
    ) -> None:
        """Escalation is otherwise assessed only during the call, and the
        last live analysis is dropped when the call ends: without this, what
        the customer said at the end (a manager demand, a refund) is missed."""
        if self._escalation_service is None:
            return
        try:
            self._escalation_service.assess(conversation, analysis.coverage, analysis.sentiment)
        except Exception:
            logger.exception("Final escalation assessment failed for call %r", conversation.call_id)

    def _stored_escalation(self, call_id: str) -> Escalation | None:
        if self._escalation_service is None:
            return None
        try:
            return self._escalation_service.get(call_id)
        except Exception:
            logger.exception("Reading the escalation for call %r failed", call_id)
            return None

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
        self._forget_live_result(call_id)
        # Open live views learn that the call has completed.
        self._live_analysis.touch(call_id)

        existing = self._post_call_summary_repository.get(call_id)
        if existing is not None:
            return existing

        conversation = self._revise_transcript(conversation)

        if conversation.utterance_count == 0:
            # e.g. busy / no-answer: nothing was said, so there is nothing to summarise.
            logger.info("Skipping post-call summary for call %r without utterances", call_id)
            return None

        try:
            analysis = self._analyze_and_save_coverage(conversation)
        except Exception:
            logger.exception("Final analysis failed for call %r", call_id)
            return None

        self._close_out_complaints(call_id, analysis.coverage)
        self._assess_final_escalation(conversation, analysis)

        try:
            summary = self._post_call_summary_service.generate_summary(
                PostCallSummaryRequest(
                    call_id=conversation.call_id,
                    conversation=conversation,
                    complaint_coverages=analysis.coverage.complaints,
                    sentiment=analysis.sentiment,
                    service_estimate=self._estimate_call(conversation),
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
        # Lets open live views pick up the summary.
        self._live_analysis.touch(call_id)
        return stored

    def _revise_transcript(self, conversation: Conversation) -> Conversation:
        """The completed call with its revised transcript, when there is
        one; on any failure the live transcript stays."""
        if self._transcript_reviser is None:
            return conversation
        try:
            utterances = self._transcript_reviser(conversation)
            if not utterances:
                return conversation
            revised = self._call_service.replace_transcript(conversation.call_id, utterances)
        except Exception:
            logger.exception(
                "Revising the transcript of call %r failed; keeping the live one",
                conversation.call_id,
            )
            return conversation
        # Open views pick up the new transcript.
        self._live_analysis.touch(conversation.call_id)
        return revised

    def _track_complaints(self, coverage: ConversationCoverage) -> None:
        if self._complaint_lifecycle_service is None:
            return
        try:
            self._complaint_lifecycle_service.sync_from_coverage(coverage)
        except Exception:
            logger.exception("Complaint lifecycle tracking failed for call %r", coverage.call_id)

    def _close_out_complaints(self, call_id: str, coverage: ConversationCoverage) -> None:
        """After the call: final complaint states, the customer link, open
        complaints flagged for follow-up, and a discovery run requested."""
        if self._complaint_lifecycle_service is not None:
            self._track_complaints(coverage)
            try:
                customer_id = (
                    self._customer_id_resolver(call_id)
                    if self._customer_id_resolver is not None
                    else None
                )
            except Exception:
                logger.exception("Resolving the customer for call %r failed", call_id)
                customer_id = None
            try:
                self._complaint_lifecycle_service.close_call(call_id, customer_id)
            except Exception:
                logger.exception("Closing out the complaints of call %r failed", call_id)

        if self._emerging_complaint_service is not None and self._emerging_complaint_auto_discovery:
            try:
                self._emerging_complaint_service.request_discovery()
            except Exception:
                logger.exception("Requesting emerging-complaint discovery failed")

    def _analyze_and_save_coverage(
        self,
        conversation: Conversation,
        still_active: Callable[[], bool] | None = None,
    ) -> ConversationAnalysisResult:
        coverage = self._coverage_repository.get(conversation.call_id)
        if coverage is None:
            coverage = ConversationCoverage(call_id=conversation.call_id)

        analysis = self._analysis_service.analyze(conversation, coverage)
        if still_active is not None and not still_active():
            raise _CallCompletedDuringAnalysis(conversation.call_id)
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
            escalation=self._stored_escalation(conversation.call_id),
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

    def _vehicle_model(self, call_id: str) -> str | None:
        if self._vehicle_model_resolver is None:
            return None
        try:
            return self._vehicle_model_resolver(call_id)
        except Exception:
            logger.warning("Could not look up the vehicle model of call %r", call_id, exc_info=True)
            return None

    def _estimate_call(self, conversation: Conversation) -> CallServiceEstimate | None:
        """Every service the call has needed so far, added up. A failure
        here never stops the rest of the analysis."""
        try:
            return self._estimation_service.estimate_call(
                conversation.utterances, self._vehicle_model(conversation.call_id)
            )
        except Exception:
            logger.exception("Service estimate failed for call %r", conversation.call_id)
            return None
