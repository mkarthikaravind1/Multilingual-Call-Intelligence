from dataclasses import dataclass

from app.ai.sentiment.provider import SentimentResult
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.sentiment_analysis_service import SentimentAnalysisService


@dataclass(frozen=True)
class ConversationAnalysisResult:
    coverage: ConversationCoverage
    sentiment: SentimentResult


class ConversationAnalysisService:
    def __init__(
        self,
        complaint_service: ComplaintAnalysisService,
        sentiment_service: SentimentAnalysisService,
    ) -> None:
        self._complaint_service = complaint_service
        self._sentiment_service = sentiment_service

    def analyze(
        self,
        conversation: Conversation,
        coverage: ConversationCoverage,
    ) -> ConversationAnalysisResult:
        if conversation.call_id != coverage.call_id:
            raise ValueError(
                "conversation.call_id must match coverage.call_id."
            )

        updated_coverage = self._complaint_service.analyze(
            conversation,
            coverage,
        )

        sentiment = self._sentiment_service.analyze(conversation)

        return ConversationAnalysisResult(
            coverage=updated_coverage,
            sentiment=sentiment,
        )