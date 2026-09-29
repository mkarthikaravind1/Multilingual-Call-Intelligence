from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.ai.sentiment.provider import SentimentResult
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import EscalationAssessment


@dataclass(frozen=True)
class EscalationContext:
    """What a detector sees: the conversation so far plus the analysis the
    call already produced for it."""

    conversation: Conversation
    coverage: ConversationCoverage
    sentiment: SentimentResult | None


class EscalationDetectionProvider(ABC):
    @abstractmethod
    def assess(self, context: EscalationContext) -> EscalationAssessment:
        raise NotImplementedError
