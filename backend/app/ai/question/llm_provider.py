import json
import logging
from typing import Any

from app.ai.learning_guidance import format_learning_guidance
from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.question.provider import (
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.core.languages import ENGLISH, is_written_in_script, language_name
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("question", "target_category", "priority", "reason")

_NO_CONVERSATION = "(no conversation available yet)"

_GUARDRAILS = (
    "The question must directly address the target complaint category.",
    "Ask for information that is still missing; do not repeat anything the conversation already states.",
    "Before you answer, check what the CUSTOMER has already said: never ask for a date, "
    "amount, bill, part, vehicle detail or event they already gave. If nothing about the "
    "target category is still missing, respond with null.",
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

_TRANSLATED_RESPONSE_SHAPE = (
    '{"question": "<string, in {language} script>", '
    '"question_en": "<the same question in English>", '
    '"target_category": "<exactly the target category above>", '
    '"priority": <non-negative integer>, '
    '"reason": "<string, in English>", '
    '"confidence": <number between 0.0 and 1.0>}'
)


class _InvalidResponse(Exception):
    pass


class LLMQuestionProvider(QuestionSuggestionProvider):
    """Suggests the next question with the LLM, in the customer's language.

    fallback (e.g. the rule-based questions) answers instead when the LLM
    fails or its answer is unusable, such as a Tamil question not written in
    Tamil script. A deliberate "nothing to ask yet" is not replaced."""

    def __init__(
        self,
        llm_client: LLMClient,
        fallback: QuestionSuggestionProvider | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._fallback = fallback

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        try:
            response = self._llm_client.complete(self._build_request(context))
            return self._parse_response(response.text, context)
        except _InvalidResponse as exc:
            logger.warning("Discarding invalid LLM question response: %s", exc)
        except Exception:
            if self._fallback is None:
                raise
            logger.exception("LLM question suggestion failed")
        if self._fallback is None:
            return None
        return self._fallback.generate(context)

    @staticmethod
    def _conversation_text(context: QuestionGenerationContext) -> str:
        # Who said what, so the model can see what the customer already told.
        return "\n".join(
            f"{u.speaker_role.value}: {text}"
            for u in context.utterances
            if (text := u.transcript.strip())
        )

    def _build_request(self, context: QuestionGenerationContext) -> LLMRequest:
        rules = "\n".join(
            f"- {rule}" for rule in (*_GUARDRAILS, *_language_rules(context))
        )
        shape = (
            _RESPONSE_SHAPE
            if context.language == ENGLISH
            else _TRANSLATED_RESPONSE_SHAPE.replace(
                "{language}", language_name(context.language)
            )
        )
        prompt = (
            "You assist a human ICR (customer service representative) during a live "
            "automotive service call. You only suggest a question; the ICR decides "
            "whether to ask it.\n\n"
            f"Target complaint category: {context.category}\n"
            f"Current complaint status: {context.status.value}\n"
            f"Conversation so far:\n{self._conversation_text(context) or _NO_CONVERSATION}\n\n"
            f"Rules:\n{rules}\n\n"
            f"{format_learning_guidance(context.learning_context)}"
            "Respond with ONLY a single JSON object and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{shape}\n"
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
            raise _InvalidResponse("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError as exc:
            raise _InvalidResponse("response is not valid JSON") from exc

        if data is None:
            return None
        if not isinstance(data, dict):
            raise _InvalidResponse("JSON response is not an object")

        try:
            return self._build_suggestion(data, context)
        except (TypeError, ValueError) as exc:
            raise _InvalidResponse(str(exc)) from exc

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

        question_en = None
        if context.language != ENGLISH:
            if not is_written_in_script(question, context.language):
                raise ValueError(
                    f"question is not written in {language_name(context.language)} script"
                )
            question_en = _require_str(data.get("question_en"), "question_en")

        return QuestionSuggestion(
            question=question,
            target_category=category,
            priority=priority,
            reason=reason,
            source=SuggestionSource.LLM,
            confidence=confidence,
            language=context.language,
            question_en=question_en,
        )


def _language_rules(context: QuestionGenerationContext) -> tuple[str, ...]:
    if context.language == ENGLISH:
        return ("Write the question in English.",)
    name = language_name(context.language)
    return (
        f'The customer speaks {name}. Write "question" in {name}, in {name} script '
        f"only, even when the customer speaks {name} in Latin letters or mixes in "
        "English. English words the customer used (e.g. part names) may be written "
        f"in {name} script as they are spoken.",
        'Write "question_en" as the same question in English, and "reason" in English.',
    )


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