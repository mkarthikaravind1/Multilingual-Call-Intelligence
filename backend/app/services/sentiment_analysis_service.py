from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentResult
from app.domain.conversation import Conversation


class SentimentAnalysisService:
    def __init__(self, provider: SentimentAnalysisProvider) -> None:
        self._provider = provider

    def analyze(self, conversation: Conversation) -> SentimentResult:
        result = self._provider.analyze(conversation)
        if not isinstance(result, SentimentResult):
            raise TypeError(
                "SentimentAnalysisProvider.analyze must return a SentimentResult, "
                f"got {type(result).__name__}."
            )
        return result