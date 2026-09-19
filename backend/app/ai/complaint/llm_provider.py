import json
import logging
from typing import Any

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.ai.llm.client import LLMClient, LLMRequest
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.conversation import Conversation

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("category", "confidence", "evidence")

_GUARDRAILS = (
    "Report only complaints clearly supported by the conversation; do not invent complaints.",
    "Report every category the conversation supports; one conversation can contain several.",
    "Report each category at most once, even if it is raised repeatedly.",
    'Use category names exactly as listed. Use "Other" only for a real complaint '
    "that fits no other category.",
    "evidence must be one concise sentence based only on what is said in the conversation.",
)

_RESPONSE_SHAPE = (
    '[{"category": "<exact category from the list>", '
    '"confidence": <number between 0.0 and 1.0>, '
    '"evidence": "<short evidence from the conversation>"}]'
)


class LLMComplaintProvider(ComplaintDetectionProvider):
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        if not conversation.utterances:
            return []
        response = self._llm_client.complete(self._build_request(conversation))
        return self._parse_response(response.text)

    @staticmethod
    def _transcript(conversation: Conversation) -> str:
        return "\n".join(
            f"{u.speaker_role.value}: {u.transcript.strip()}"
            for u in conversation.utterances
        )

    def _build_request(self, conversation: Conversation) -> LLMRequest:
        categories = "\n".join(f"- {category}" for category in COMPLAINT_CATEGORIES)
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        prompt = (
            "You analyse a transcript of a live automotive service call between an ICR "
            "(customer service representative) and a customer, and identify the "
            "complaints the customer has raised.\n\n"
            f"Complaint categories:\n{categories}\n\n"
            f"Conversation:\n{self._transcript(conversation)}\n\n"
            f"Rules:\n{rules}\n\n"
            "Respond with ONLY a JSON array and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{_RESPONSE_SHAPE}\n"
            "confidence must be a number between 0.0 and 1.0, not text.\n"
            "If the conversation contains no supported complaints, respond with exactly: []"
        )
        return LLMRequest(prompt=prompt)

    def _parse_response(self, text: str) -> list[ComplaintDetectionResult]:
        if not isinstance(text, str):
            return self._reject("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError:
            return self._reject("response is not valid JSON")

        if not isinstance(data, list):
            return self._reject("JSON response is not a list")

        try:
            results = [self._build_result(item) for item in data]
        except (TypeError, ValueError) as exc:
            return self._reject(str(exc))

        if len({r.category for r in results}) != len(results):
            return self._reject("duplicate categories in response")
        return results

    @staticmethod
    def _build_result(item: Any) -> ComplaintDetectionResult:
        if not isinstance(item, dict):
            raise TypeError("each item must be an object")

        missing = [f for f in _REQUIRED_FIELDS if f not in item]
        if missing:
            raise ValueError(f"missing fields: {missing}")

        evidence = item["evidence"]
        if not isinstance(evidence, str):
            raise TypeError("evidence must be a string")

        return ComplaintDetectionResult(
            category=item["category"],
            confidence=item["confidence"],
            evidence=evidence.strip(),
        )

    @staticmethod
    def _reject(reason: str) -> list[ComplaintDetectionResult]:
        logger.warning("Discarding invalid LLM complaint response: %s", reason)
        return []


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()