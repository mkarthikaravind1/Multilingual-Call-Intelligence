from dataclasses import dataclass

from app.ai.complaint.provider import UtteranceCategories, line_categories
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.sentiment.provider import SentimentResult
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import EscalationSignal
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.sentiment_analysis_service import SentimentAnalysisService


@dataclass(frozen=True)
class ConversationAnalysisResult:
    coverage: ConversationCoverage
    sentiment: SentimentResult
    # The LLM's escalation signals when a combined live-analysis request
    # found them; None: the escalation detector asks on its own.
    escalation_signals: tuple[EscalationSignal, ...] | None = None
    # The complaint categories each line raises; None when the complaint
    # detection did not say (the lines keep what they have).
    line_categories: tuple[UtteranceCategories, ...] | None = None


class ConversationAnalysisService:
    def __init__(
        self,
        complaint_service: ComplaintAnalysisService,
        sentiment_service: SentimentAnalysisService,
        live_analyzer: LLMLiveAnalysisProvider | None = None,
    ) -> None:
        self._complaint_service = complaint_service
        self._sentiment_service = sentiment_service
        # LIVE_ANALYSIS_MODE=combined: one request during a call (None:
        # separate requests). A call's final analysis is always separate.
        self._live_analyzer = live_analyzer

    def analyze(
        self,
        conversation: Conversation,
        coverage: ConversationCoverage,
        *,
        live: bool = False,
    ) -> ConversationAnalysisResult:
        if conversation.call_id != coverage.call_id:
            raise ValueError(
                "conversation.call_id must match coverage.call_id."
            )
        if live and self._live_analyzer is not None and conversation.utterances:
            return self._analyze_together(conversation, coverage)

        updated_coverage, detections = self._complaint_service.analyze_with_detections(
            conversation,
            coverage,
        )

        sentiment = self._sentiment_service.analyze(conversation)

        return ConversationAnalysisResult(
            coverage=updated_coverage,
            sentiment=sentiment,
            line_categories=line_categories(conversation, detections),
        )

    def _analyze_together(
        self, conversation: Conversation, coverage: ConversationCoverage
    ) -> ConversationAnalysisResult:
        complaint_guidance = self._complaint_service.guidance()
        sentiment_guidance = self._sentiment_service.guidance()
        together = self._live_analyzer.analyze(
            conversation, complaint_guidance, sentiment_guidance
        )
        # A section the combined answer lacks is asked for on its own.
        if together.complaints is None:
            updated_coverage, detections = self._complaint_service.analyze_with_detections(
                conversation, coverage
            )
        else:
            detections = together.complaints
            updated_coverage = self._complaint_service.apply(
                conversation, coverage, detections, complaint_guidance
            )
        sentiment = (
            self._sentiment_service.analyze(conversation)
            if together.sentiment is None
            else self._sentiment_service.accept(
                conversation, together.sentiment, sentiment_guidance
            )
        )
        return ConversationAnalysisResult(
            coverage=updated_coverage,
            sentiment=sentiment,
            escalation_signals=together.escalation_signals,
            line_categories=line_categories(conversation, detections),
        )