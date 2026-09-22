from app.ai.summary.provider import PostCallSummaryRequest, SummaryGenerationProvider
from app.domain.post_call_summary import PostCallSummary


class PostCallSummaryService:
    """Thin orchestration layer: delegates summary generation to an
    injected SummaryGenerationProvider and validates its result."""

    def __init__(self, provider: SummaryGenerationProvider):
        self._provider = provider

    def generate_summary(self, request: PostCallSummaryRequest) -> PostCallSummary | None:
        if request.call_id != request.conversation.call_id:
            raise ValueError(
                "call_id mismatch: request.call_id "
                f"({request.call_id!r}) != request.conversation.call_id "
                f"({request.conversation.call_id!r})."
            )

        result = self._provider.generate_summary(request)

        if result is not None and not isinstance(result, PostCallSummary):
            raise TypeError(
                f"Provider must return a PostCallSummary or None, got {type(result).__name__}."
            )

        return result