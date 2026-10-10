import logging
import time
from typing import Callable, TypeVar

from app.ai.llm.client import rate_limit_in
from app.ai.summary.provider import PostCallSummaryRequest
from app.domain.conversation import Conversation, ConversationStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.customer_contact import CustomerContact
from app.domain.post_call_summary import PostCallSummary
from app.domain.service_estimate import CallServiceEstimate
from app.domain.utterance import Utterance
from app.services.best_effort import best_effort
from app.services.call_service import CallService
from app.services.complaint_lifecycle_service import ComplaintLifecycleService
from app.services.conversation_analysis_service import (
    ConversationAnalysisResult,
    ConversationAnalysisService,
)
from app.services.conversation_coverage_repository import (
    ConversationCoverageRepository,
)
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryService
from app.services.emerging_complaint_service import EmergingComplaintService
from app.services.escalation_service import EscalationService
from app.services.live_analysis_store import LiveAnalysisStore
from app.services.post_call_summary_repository import PostCallSummaryRepository
from app.services.post_call_summary_service import PostCallSummaryService

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_RATE_LIMIT_ATTEMPTS = 3
# Waits longer than this (a daily limit) are left to the repair job.
_MAX_RATE_LIMIT_WAIT_SECONDS = 60.0
_DEFAULT_RATE_LIMIT_WAIT_SECONDS = 20.0


class PostCallProcessor:
    """What happens once a call has completed: the revised transcript, the
    final analysis, closing out its complaints, the last escalation check,
    and the post-call summary (generated, stored and delivered)."""

    def __init__(
        self,
        *,
        call_service: CallService,
        coverage_repository: ConversationCoverageRepository,
        analysis_service: ConversationAnalysisService,
        post_call_summary_service: PostCallSummaryService,
        post_call_summary_repository: PostCallSummaryRepository,
        live_analysis: LiveAnalysisStore,
        forget_live_result: Callable[[str], None],
        estimate: Callable[[Conversation], CallServiceEstimate | None],
        customer_summary_delivery_service: CustomerSummaryDeliveryService | None = None,
        customer_contact_resolver: Callable[[str], CustomerContact | None] | None = None,
        customer_summary_enabled: bool = False,
        escalation_service: EscalationService | None = None,
        complaint_lifecycle_service: ComplaintLifecycleService | None = None,
        customer_id_resolver: Callable[[str], str | None] | None = None,
        emerging_complaint_service: EmergingComplaintService | None = None,
        emerging_complaint_auto_discovery: bool = False,
        transcript_reviser: Callable[[Conversation], tuple[Utterance, ...] | None]
        | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Waits out a short LLM rate limit.
        self._sleep = sleep
        # A better transcript of the whole call (e.g. from its recording,
        # see PostCallRetranscriptionService), or None.
        self._transcript_reviser = transcript_reviser
        self._escalation_service = escalation_service
        self._complaint_lifecycle_service = complaint_lifecycle_service
        self._customer_id_resolver = customer_id_resolver
        self._emerging_complaint_service = emerging_complaint_service
        self._emerging_complaint_auto_discovery = emerging_complaint_auto_discovery
        self._call_service = call_service
        self._coverage_repository = coverage_repository
        self._analysis_service = analysis_service
        self._post_call_summary_service = post_call_summary_service
        self._post_call_summary_repository = post_call_summary_repository
        self._customer_summary_delivery_service = customer_summary_delivery_service
        self._customer_contact_resolver = customer_contact_resolver
        self._customer_summary_enabled = customer_summary_enabled
        self._live_analysis = live_analysis
        self._forget_live_result = forget_live_result
        self._estimate = estimate

    def process(self, call_id: str) -> PostCallSummary | None:
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
            analysis = self._waiting_out_rate_limits(
                call_id, lambda: self._analyze_and_save_coverage(conversation)
            )
        except Exception:
            logger.exception("Final analysis failed for call %r", call_id)
            return None

        self._close_out_complaints(call_id, analysis.coverage)
        self._assess_final_escalation(conversation, analysis)

        request = PostCallSummaryRequest(
            call_id=conversation.call_id,
            conversation=conversation,
            complaint_coverages=analysis.coverage.complaints,
            sentiment=analysis.sentiment,
            service_estimate=self._estimate(conversation),
        )
        try:
            summary = self._waiting_out_rate_limits(
                call_id, lambda: self._post_call_summary_service.generate_summary(request)
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

    def _waiting_out_rate_limits(self, call_id: str, step: Callable[[], _T]) -> _T:
        """Run a post-call step, waiting and trying again (at most
        _RATE_LIMIT_ATTEMPTS times) while the LLM is rate limited for a
        short while: the call's last live analysis often used the minute's
        tokens. A longer limit (e.g. the daily one) is left to the post-call
        repair job."""
        for attempt in range(1, _RATE_LIMIT_ATTEMPTS + 1):
            try:
                return step()
            except Exception as exc:
                limited = rate_limit_in(exc)
                wait = None if limited is None else limited.retry_after_seconds
                if wait is None and limited is not None:
                    wait = _DEFAULT_RATE_LIMIT_WAIT_SECONDS
                if wait is None or wait > _MAX_RATE_LIMIT_WAIT_SECONDS or attempt == _RATE_LIMIT_ATTEMPTS:
                    raise
                logger.info(
                    "LLM rate limited during post-call processing of call %r; "
                    "trying again in %.0f s",
                    call_id,
                    wait,
                )
                self._sleep(wait + 1.0)
        raise AssertionError("unreachable")

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

    def _analyze_and_save_coverage(self, conversation: Conversation) -> ConversationAnalysisResult:
        """The final analysis: always separate requests, never the combined
        one a live call may use."""
        coverage = self._coverage_repository.get(conversation.call_id)
        if coverage is None:
            coverage = ConversationCoverage(call_id=conversation.call_id)

        analysis = self._analysis_service.analyze(conversation, coverage, live=False)
        self._coverage_repository.save(analysis.coverage)
        return analysis

    def _close_out_complaints(self, call_id: str, coverage: ConversationCoverage) -> None:
        """Final complaint states, the customer link, open complaints
        flagged for follow-up, and a discovery run requested."""
        if self._complaint_lifecycle_service is not None:
            best_effort(
                "Complaint lifecycle tracking", call_id,
                self._complaint_lifecycle_service.sync_from_coverage, coverage,
            )
            customer_id = (
                best_effort("Resolving the customer", call_id, self._customer_id_resolver, call_id)
                if self._customer_id_resolver is not None
                else None
            )
            best_effort(
                "Closing out the complaints", call_id,
                self._complaint_lifecycle_service.close_call, call_id, customer_id,
            )

        if self._emerging_complaint_service is not None and self._emerging_complaint_auto_discovery:
            best_effort(
                "Requesting emerging-complaint discovery", call_id,
                self._emerging_complaint_service.request_discovery,
            )

    def _assess_final_escalation(
        self, conversation: Conversation, analysis: ConversationAnalysisResult
    ) -> None:
        """Escalation is otherwise assessed only during the call, and the
        last live analysis is dropped when the call ends: without this, what
        the customer said at the end (a manager demand, a refund) is missed."""
        if self._escalation_service is None:
            return
        best_effort(
            "Final escalation assessment", conversation.call_id,
            self._escalation_service.assess, conversation, analysis.coverage, analysis.sentiment,
        )

    def _deliver_summary(self, summary: PostCallSummary) -> None:
        if (
            not self._customer_summary_enabled
            or self._customer_summary_delivery_service is None
            or self._customer_contact_resolver is None
        ):
            return

        def deliver() -> None:
            contact = self._customer_contact_resolver(summary.call_id)
            if contact is not None:
                self._customer_summary_delivery_service.send_summary_to_customer(
                    summary=summary,
                    contact=contact,
                )

        best_effort("Customer summary delivery", summary.call_id, deliver)
