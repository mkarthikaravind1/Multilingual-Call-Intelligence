import logging
from typing import Any

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.ai.learning_guidance import format_learning_guidance
from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.llm.json_answer import UnusableAnswer, ask_for_json, decode_json
from app.ai.llm.transcript import numbered_transcript
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
    "probed is true only when the ICR has asked the customer at least one question about "
    "that complaint (to understand or resolve it); an apology or a promise alone is not "
    "a question.",
    "lines lists the numbers (shown in square brackets) of the conversation lines in which "
    "the customer raises or describes that complaint. A line that covers several complaints "
    "is listed under each of them.",
)

_RESPONSE_SHAPE = (
    '[{"category": "<exact category from the list>", '
    '"confidence": <number between 0.0 and 1.0>, '
    '"evidence": "<short evidence from the conversation>", '
    '"probed": <true or false>, '
    '"lines": [<line number>, ...]}]'
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
        allowed = {c.name for c in categories}
        try:
            return ask_for_json(
                self._llm_client,
                self._build_request(conversation, learning_context, categories),
                lambda text: self._parse_answer(text, allowed),
                "complaints",
            )
        except UnusableAnswer:
            return []

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
            f"Conversation:\n{numbered_transcript(conversation)}\n\n"
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
        # One per category, in the order first reported.
        results: dict[str, ComplaintDetectionResult] = {}
        malformed = 0
        for item in data:
            try:
                result = self._build_result(item, canonical)
            except (TypeError, ValueError) as exc:
                # One bad item does not cost the complaints reported beside it.
                malformed += 1
                logger.warning("Skipping a malformed LLM complaint item: %s", exc)
                continue
            if result is not None:
                results[result.category] = _merged(results.get(result.category), result)

        if malformed and not results:
            self._reject("no usable items in response")
            return None
        return list(results.values())

    def _parse_answer(self, text: Any, allowed: set[str]) -> list[ComplaintDetectionResult]:
        results = self.parse_items(decode_json(text), allowed)
        if results is None:
            raise UnusableAnswer("the answer is not a usable list of complaints")
        return results

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
            # Extra: an answer without it (or with something else there)
            # is still a detection, of a complaint not yet asked about.
            probed=_is_true(item.get("probed")),
            lines=_line_numbers(item.get("lines")),
        )

    @staticmethod
    def _reject(reason: str) -> None:
        logger.warning("Discarding invalid LLM complaint response: %s", reason)


def _is_true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes")
    return value is True


def _category_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _merged(
    first: ComplaintDetectionResult | None, again: ComplaintDetectionResult
) -> ComplaintDetectionResult:
    """One result for a category the answer reports twice: the more
    confident report, asked about if either says so."""
    if first is None:
        return again
    best = again if again.confidence > first.confidence else first
    return ComplaintDetectionResult(
        category=best.category,
        confidence=best.confidence,
        evidence=best.evidence,
        probed=first.probed or again.probed,
        lines=tuple(dict.fromkeys(first.lines + again.lines)),
    )


def _line_numbers(value: Any) -> tuple[int, ...]:
    """The usable line numbers in an answer's "lines". They are extra: a
    missing or malformed list (or entry) is left out and never spoils the
    complaint. Whether a number is a line of the call is checked when the
    lines are tagged (see line_categories)."""
    if not isinstance(value, list):
        return ()
    numbers = []
    for entry in value:
        if isinstance(entry, bool):
            continue
        if isinstance(entry, str) and entry.strip().isdigit():
            entry = int(entry.strip())
        if isinstance(entry, int) and entry > 0:
            numbers.append(entry)
    return tuple(dict.fromkeys(numbers))