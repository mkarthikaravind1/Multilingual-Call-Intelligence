import json
from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource

class LLMQuestionProvider(QuestionSuggestionProvider):
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        request = self._build_request(context)
        response = self._llm_client.complete(request)
        return self._parse_response(response.text)

    def _build_request(self, context: QuestionGenerationContext) -> LLMRequest:
        transcript = " ".join(u.transcript for u in context.utterances)
        prompt = (
            f"Complaint category: {context.category}\n"
            f"Complaint status: {context.status.value}\n"
            f"Relevant conversation: {transcript}\n"
            "Respond as JSON with keys: question, target_category, priority, reason, confidence."
        )
        return LLMRequest(prompt=prompt)

    def _parse_response(self, text: str) -> QuestionSuggestion | None:
        try:
            data = json.loads(text)
            return QuestionSuggestion(
                question=data["question"],
                target_category=data["target_category"],
                priority=data["priority"],
                reason=data["reason"],
                source=SuggestionSource.LLM,
                confidence=data.get("confidence"),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None