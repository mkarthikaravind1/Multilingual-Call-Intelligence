"""Which services from the price list a call is about.

Detectors only name services. Prices always come from the price list
(PricingConfig), never from a detector, so an LLM cannot invent a cost.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.ai.llm.client import LLMClient, LLMRequest
from app.domain.utterance import Utterance
from app.estimation.pricing_config import PricingConfig

logger = logging.getLogger(__name__)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_MAX_LINES = 60
_MAX_LINE_CHARS = 400


class ServiceDetectionProvider(ABC):
    @abstractmethod
    def detect(self, utterances: Sequence[Utterance]) -> list[str]:
        """The price-list service names the call needs, in the order they
        came up."""
        raise NotImplementedError


class KeywordServiceDetector(ServiceDetectionProvider):
    """Every service whose keyword is said anywhere in the call (English
    keywords; it cannot tell "the battery is fine" from a battery fault)."""

    def __init__(self, pricing: PricingConfig) -> None:
        self._pricing = pricing

    def detect(self, utterances: Sequence[Utterance]) -> list[str]:
        found: list[str] = []
        for utterance in utterances:
            text = utterance.transcript.casefold()
            for rule in self._pricing.rules:
                if rule.service_name not in found and any(
                    keyword.casefold() in text for keyword in rule.keywords
                ):
                    found.append(rule.service_name)
        return found


class LLMServiceDetector(ServiceDetectionProvider):
    """Reads the conversation like a service advisor would: services the
    customer needs or asks for, or that the ICR agrees to do, in any of the
    supported languages; not ones that are declined or ruled out. Falls back
    to the keyword detector when the LLM fails."""

    def __init__(
        self,
        llm_client: LLMClient,
        pricing: PricingConfig,
        fallback: ServiceDetectionProvider | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._pricing = pricing
        self._fallback = fallback or KeywordServiceDetector(pricing)

    def detect(self, utterances: Sequence[Utterance]) -> list[str]:
        if not utterances:
            return []
        try:
            response = self._llm_client.complete(LLMRequest(prompt=self._prompt(utterances)))
            return self._parse(response.text or "")
        except Exception:
            logger.warning(
                "LLM service detection failed; using the price-list keywords.", exc_info=True
            )
            return self._fallback.detect(utterances)

    def _prompt(self, utterances: Sequence[Utterance]) -> str:
        catalogue = "\n".join(
            f'- "{rule.service_name}" (e.g. {", ".join(rule.keywords)})'
            for rule in self._pricing.rules
        )
        transcript = "\n".join(
            f"{u.speaker_role.value}: {u.transcript.strip()[:_MAX_LINE_CHARS]}"
            for u in utterances[-_MAX_LINES:]
        )
        return (
            "You read a phone call between an ICR (the representative of an automotive "
            "service centre) and a customer, to work out which services from the price "
            "list the customer's vehicle needs. The call may be in Tamil, Telugu, Kannada, "
            "Malayalam, English or a mix; UNKNOWN lines are from either speaker.\n\n"
            f"Price list services:\n{catalogue}\n\n"
            f"Conversation:\n{transcript}\n\n"
            "Rules:\n"
            "- Include a service when the customer describes a problem it fixes, asks for "
            "it, or the ICR agrees or books to do it.\n"
            "- Do not include a service that is ruled out or declined (e.g. \"the battery "
            "is fine\", \"no need for an oil change\"), or only offered and not taken up.\n"
            "- Use only the exact service names from the price list; never invent one.\n"
            "- List them in the order they came up in the call.\n"
            'Reply with JSON only: {"services": ["<service name>", ...]}'
        )

    def _parse(self, text: str) -> list[str]:
        match = _JSON_OBJECT.search(text)
        if match is None:
            raise ValueError("The LLM reply holds no JSON object.")
        payload = json.loads(match.group(0))
        names = payload.get("services") if isinstance(payload, dict) else None
        if not isinstance(names, list):
            raise ValueError("The LLM reply has no services list.")
        found: list[str] = []
        for name in names:
            rule = self._pricing.rule_for(name) if isinstance(name, str) else None
            if rule is not None and rule.service_name not in found:
                found.append(rule.service_name)
        return found
