import json
import logging
from typing import Any

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.ai.learning_guidance import format_learning_guidance
from app.ai.llm.client import LLMClient, LLMRequest
from app.domain.complaint_category import ComplaintCategory
from app.domain.conversation import Conversation
from app.domain.runtime_improvement_context import RuntimeImprovementContext
from app.services.complaint_category_catalog import BUILT_IN_CATALOG, ComplaintCategoryCatalog

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
    """Asks the LLM which of the catalog's categories (the built-ins plus
    accepted emerging themes) the customer raised."""

    def __init__(
        self, llm_client: LLMClient, catalog: ComplaintCategoryCatalog | None = None
    ) -> None:
        self._llm_client = llm_client
        self._catalog = catalog or BUILT_IN_CATALOG

    def detect(
        self,
        conversation: Conversation,
        learning_context: tuple[RuntimeImprovementContext, ...] = (),
    ) -> list[ComplaintDetectionResult]:
        if not conversation.utterances:
            return []
        categories = self._catalog.categories()
        response = self._llm_client.complete(
            self._build_request(conversation, learning_context, categories)
        )
        return self._parse_response(response.text, {c.name for c in categories})

    @staticmethod
    def _transcript(conversation: Conversation) -> str:
        return "\n".join(
            f"{u.speaker_role.value}: {u.transcript.strip()}"
            for u in conversation.utterances
        )

    def _build_request(
        self,
        conversation: Conversation,
        learning_context: tuple[RuntimeImprovementContext, ...] = (),
        known: tuple[ComplaintCategory, ...] | None = None,
    ) -> LLMRequest:
        if known is None:
            known = self._catalog.categories()
        # Accepted themes carry what counts as them; built-ins speak for themselves.
        categories = "\n".join(
            f"- {c.name}: {c.description}" if c.description else f"- {c.name}" for c in known
        )
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        prompt = (
            "You analyse a transcript of a live automotive service call between an ICR "
            "(customer service representative) and a customer, and identify the "
            "complaints the customer has raised.\n\n"
            f"Complaint categories:\n{categories}\n\n"
            f"Conversation:\n{self._transcript(conversation)}\n\n"
            f"Rules:\n{rules}\n\n"
            f"{format_learning_guidance(learning_context)}"
            "Respond with ONLY a JSON array and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{_RESPONSE_SHAPE}\n"
            "confidence must be a number between 0.0 and 1.0, not text.\n"
            "If the conversation contains no supported complaints, respond with exactly: []"
        )
        return LLMRequest(prompt=prompt)

    @property
    def llm_client(self) -> LLMClient:
        return self._llm_client

    def task_instructions(
        self, learning_context: tuple[RuntimeImprovementContext, ...] = ()
    ) -> tuple[str, set[str]]:
        """This provider's task inside a combined live-analysis request (see
        LLMLiveAnalysisProvider): the same categories, rules and guidance as
        detect()'s own prompt. Also returns the category names it may report."""
        known = self._catalog.categories()
        categories = "\n".join(
            f"- {c.name}: {c.description}" if c.description else f"- {c.name}" for c in known
        )
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        text = (
            f"Complaint categories:\n{categories}\n\n"
            f"Rules:\n{rules}\n\n"
            f"{format_learning_guidance(learning_context)}"
            f'"complaints" is a JSON array in exactly this shape:\n{_RESPONSE_SHAPE}\n'
            'If the conversation contains no supported complaints, "complaints" is [].'
        )
        return text, {c.name for c in known}

    def parse_items(
        self, data: Any, allowed: set[str]
    ) -> list[ComplaintDetectionResult] | None:
        """The detections in a decoded answer, checked as detect() checks
        them; None when the answer is unusable."""
        if not isinstance(data, list):
            self._reject("JSON response is not a list")
            return None

        # The model may change a category's case or spacing ("wiper noise");
        # match it to the catalog's spelling.
        canonical = {_category_key(name): name for name in allowed}
        try:
            built = [self._build_result(item, canonical) for item in data]
        except (TypeError, ValueError) as exc:
            self._reject(str(exc))
            return None
        results = [result for result in built if result is not None]

        if len({r.category for r in results}) != len(results):
            self._reject("duplicate categories in response")
            return None
        return results

    def _parse_response(
        self, text: str, allowed: set[str] | None = None
    ) -> list[ComplaintDetectionResult]:
        if allowed is None:
            allowed = set(self._catalog.names())
        if not isinstance(text, str):
            return self._reject("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError:
            return self._reject("response is not valid JSON")
        return self.parse_items(data, allowed) or []

    @staticmethod
    def _build_result(
        item: Any, canonical: dict[str, str]
    ) -> ComplaintDetectionResult | None:
        """The result for one item; None for a category the catalog does not
        have, which is skipped so the other complaints in the answer are kept."""
        if not isinstance(item, dict):
            raise TypeError("each item must be an object")

        missing = [f for f in _REQUIRED_FIELDS if f not in item]
        if missing:
            raise ValueError(f"missing fields: {missing}")

        evidence = item["evidence"]
        if not isinstance(evidence, str):
            raise TypeError("evidence must be a string")
        if not isinstance(item["category"], str):
            raise TypeError("category must be a string")
        category = canonical.get(_category_key(item["category"]))
        if category is None:
            logger.warning(
                "Skipping LLM complaint with an unknown category: %r", item["category"]
            )
            return None

        return ComplaintDetectionResult(
            category=category,
            confidence=item["confidence"],
            evidence=evidence.strip(),
        )

    @staticmethod
    def _reject(reason: str) -> list[ComplaintDetectionResult]:
        logger.warning("Discarding invalid LLM complaint response: %s", reason)
        return []


def _category_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()