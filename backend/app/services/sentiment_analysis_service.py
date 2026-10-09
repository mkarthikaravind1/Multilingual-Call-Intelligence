from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentResult
from app.domain.conversation import Conversation
from app.services.runtime_improvement_service import ComponentLearning


class SentimentAnalysisService:
    def __init__(
        self,
        provider: SentimentAnalysisProvider,
        learning: ComponentLearning | None = None,
    ) -> None:
        self._provider = provider
        self._learning = learning

    def analyze(self, conversation: Conversation) -> SentimentResult:
        contexts = self.guidance()
        # Approved guidance is passed only when there is some, so providers
        # written against the one-argument form keep working unchanged.
        result = (
            self._provider.analyze(conversation, contexts)
            if contexts
            else self._provider.analyze(conversation)
        )
        return self.accept(conversation, result, contexts)

    def guidance(self) -> tuple:
        """The approved learning guidance for sentiment analysis."""
        return self._learning.contexts() if self._learning is not None else ()

    def accept(
        self, conversation: Conversation, result: SentimentResult, contexts: tuple = ()
    ) -> SentimentResult:
        """A result made with `contexts` (here or in a combined live-analysis
        request), checked and recorded for the learning loop."""
        if not isinstance(result, SentimentResult):
            raise TypeError(
                "SentimentAnalysisProvider.analyze must return a SentimentResult, "
                f"got {type(result).__name__}."
            )
        if self._learning is not None:
            self._learning.record_usage(conversation.call_id, contexts, result.label.value)
        return result
