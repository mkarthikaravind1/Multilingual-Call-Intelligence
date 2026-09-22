from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.ai.sentiment.provider import SentimentResult
from app.domain.complaint_coverage import ComplaintCoverage
from app.domain.conversation import Conversation
from app.domain.post_call_summary import PostCallSummary
from app.domain.service_estimate import ServiceEstimate


@dataclass(frozen=True)
class PostCallSummaryRequest:
    """Bundles everything a provider needs to produce a PostCallSummary."""

    call_id: str
    conversation: Conversation
    complaint_coverages: tuple[ComplaintCoverage, ...]
    sentiment: SentimentResult
    service_estimate: ServiceEstimate | None = None

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if not isinstance(self.conversation, Conversation):
            raise TypeError(
                f"conversation must be a Conversation, got {type(self.conversation).__name__}."
            )
        if not isinstance(self.complaint_coverages, tuple) or not all(
            isinstance(c, ComplaintCoverage) for c in self.complaint_coverages
        ):
            raise ValueError("complaint_coverages must be a tuple of ComplaintCoverage.")
        if not isinstance(self.sentiment, SentimentResult):
            raise TypeError(
                f"sentiment must be a SentimentResult, got {type(self.sentiment).__name__}."
            )


class SummaryGenerationProvider(ABC):
    @abstractmethod
    def generate_summary(self, request: PostCallSummaryRequest) -> PostCallSummary | None:
        raise NotImplementedError