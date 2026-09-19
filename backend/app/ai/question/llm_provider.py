import json
import logging
from typing import Any

from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.question.provider import (
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("question", "target_category", "priority", "reason")

_NO_CONVERSATION = "(no conversation available yet)"

_GUARDRAILS = (
    "The question must directly address the target complaint category.",
    "Ask for information that is still missing; do not repeat anything the conversation already states.",
    "The question is a suggestion for the ICR to ask the customer. Do not write as the ICR: "
    "no greetings, apologies, promises or statements on behalf of the company.",
    "Do not invent facts that are not present in the conversation.",
    "Do not ask about any other complaint category.",
    "Respect the current complaint status when choosing what to ask.",
    "Keep the question concise and natural.",
)

_RESPONSE_SHAPE = (
    '{"question": "<string>", '
    '"target_category": "<exactly the target category above>", '
    '"priority": <non-negative integer>, '
    '"reason": "<string>", '
    '"confidence": <number between 0.0 and 1.0>}'
)


class LLMQuestionProvider(QuestionSuggestionProvider):
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        response = self._llm_client.complete(self._build_request(context))
        return self._parse_response(response.text, context)

    @staticmethod
    def _conversation_text(context: QuestionGenerationContext) -> str:
        return "\n".join(
            text for u in context.utterances if (text := u.transcript.strip())
        )

    def _build_request(self, context: QuestionGenerationContext) -> LLMRequest:
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        prompt = (
            "You assist a human ICR (customer service representative) during a live "
            "automotive service call. You only suggest a question; the ICR decides "
            "whether to ask it.\n\n"
            f"Target complaint category: {context.category}\n"
            f"Current complaint status: {context.status.value}\n"
            f"Conversation so far:\n{self._conversation_text(context) or _NO_CONVERSATION}\n\n"
            f"Rules:\n{rules}\n\n"
            "Respond with ONLY a single JSON object and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{_RESPONSE_SHAPE}\n"
            "priority must be a non-negative whole number and confidence a number "
            "between 0.0 and 1.0, not text.\n"
            "If the conversation does not contain enough information to ask a "
            "meaningful question, respond with exactly: null"
        )
        return LLMRequest(prompt=prompt)

    def _parse_response(
        self, text: str, context: QuestionGenerationContext
    ) -> QuestionSuggestion | None:
        if not isinstance(text, str):
            return self._reject("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError:
            return self._reject("response is not valid JSON")

        if data is None:
            return None
        if not isinstance(data, dict):
            return self._reject("JSON response is not an object")

        try:
            return self._build_suggestion(data, context)
        except (TypeError, ValueError) as exc:
            return self._reject(str(exc))

    @staticmethod
    def _build_suggestion(
        data: dict[str, Any], context: QuestionGenerationContext
    ) -> QuestionSuggestion:
        missing = [f for f in _REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"missing fields: {missing}")

        question = _require_str(data["question"], "question")
        reason = _require_str(data["reason"], "reason")
        category = _require_str(data["target_category"], "target_category")
        if category != context.category:
            raise ValueError(
                f"target_category {category!r} does not match {context.category!r}"
            )

        priority = data["priority"]
        if isinstance(priority, bool):
            raise ValueError("priority must be an integer")

        confidence = data.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise ValueError("confidence must be a number")
            confidence = float(confidence)

        return QuestionSuggestion(
            question=question,
            target_category=category,
            priority=priority,
            reason=reason,
            source=SuggestionSource.LLM,
            confidence=confidence,
        )

    @staticmethod
    def _reject(reason: str) -> None:
        logger.warning("Discarding invalid LLM question response: %s", reason)
        return None


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value.strip()


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()