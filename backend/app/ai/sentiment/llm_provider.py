import json
import logging
from typing import Any

from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.domain.conversation import Conversation

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("label", "confidence", "evidence")

_NO_CONTENT_EVIDENCE = "No conversation content is available to determine sentiment."
_UNDETERMINED_EVIDENCE = "Sentiment could not be determined from the model response."

_GUARDRAILS = (
    "Analyse only the conversation provided; do not invent facts.",
    "Determine the customer's overall sentiment across the whole conversation.",
    "Do not let a single positive or negative sentence decide the label when the "
    "complete conversation suggests otherwise.",
    "Use exactly one label: POSITIVE, NEUTRAL or NEGATIVE.",
    "evidence must be one concise sentence explaining the sentiment using only "
    "information present in the conversation; it must not contain invented information.",
)

_RESPONSE_SHAPE = (
    '{"label": "<POSITIVE | NEUTRAL | NEGATIVE>", '
    '"confidence": <number between 0.0 and 1.0>, '
    '"evidence": "<short evidence from the conversation>"}'
)


class LLMSentimentProvider(SentimentAnalysisProvider):
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def analyze(self, conversation: Conversation) -> SentimentResult:
        if not conversation.utterances:
            return SentimentResult(SentimentLabel.NEUTRAL, 0.0, _NO_CONTENT_EVIDENCE)
        response = self._llm_client.complete(self._build_request(conversation))
        return self._parse_response(response.text)

    @staticmethod
    def _transcript(conversation: Conversation) -> str:
        return "\n".join(
            f"{u.speaker_role.value}: {u.transcript.strip()}"
            for u in conversation.utterances
        )

    def _build_request(self, conversation: Conversation) -> LLMRequest:
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        prompt = (
            "You analyse a transcript of an automotive service call between an ICR "
            "(customer service representative) and a customer, and determine the "
            "overall sentiment of the conversation.\n\n"
            f"Conversation:\n{self._transcript(conversation)}\n\n"
            f"Rules:\n{rules}\n\n"
            "Respond with ONLY a single JSON object and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{_RESPONSE_SHAPE}\n"
            "confidence must be a number between 0.0 and 1.0, not text."
        )
        return LLMRequest(prompt=prompt)

    def _parse_response(self, text: str) -> SentimentResult:
        if not isinstance(text, str):
            return self._reject("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError:
            return self._reject("response is not valid JSON")

        if not isinstance(data, dict):
            return self._reject("JSON response is not an object")

        try:
            return self._build_result(data)
        except (TypeError, ValueError) as exc:
            return self._reject(str(exc))

    @staticmethod
    def _build_result(data: dict[str, Any]) -> SentimentResult:
        missing = [f for f in _REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"missing fields: {missing}")

        evidence = data["evidence"]
        if not isinstance(evidence, str):
            raise TypeError("evidence must be a string")

        return SentimentResult(
            label=SentimentLabel(data["label"]),
            confidence=data["confidence"],
            evidence=evidence.strip(),
        )

    @staticmethod
    def _reject(reason: str) -> SentimentResult:
        logger.warning("Discarding invalid LLM sentiment response: %s", reason)
        return SentimentResult(SentimentLabel.NEUTRAL, 0.0, _UNDETERMINED_EVIDENCE)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()