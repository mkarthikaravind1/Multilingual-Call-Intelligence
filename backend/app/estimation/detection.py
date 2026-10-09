"""Which services from the price list a call is about, and which vehicle
model the call names.

Detectors only name services. Prices always come from the price list
(PricingConfig), never from a detector, so an LLM cannot invent a cost.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from app.ai.llm.client import LLMClient, LLMRequest
from app.domain.utterance import Utterance
from app.estimation.pricing_config import PricingSource, normalize_model, pricing_source

logger = logging.getLogger(__name__)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_MAX_LINES = 60
_MAX_LINE_CHARS = 400
_MAX_MODELS_IN_PROMPT = 200


@dataclass(frozen=True)
class ServiceDetection:
    # Price-list service names, in the order they came up.
    services: list[str]
    # A price-list vehicle model the call names; None when it names none.
    vehicle_model: str | None = None


class ServiceDetectionProvider(ABC):
    @abstractmethod
    def detect(self, utterances: Sequence[Utterance]) -> list[str]:
        """The price-list service names the call needs, in the order they
        came up."""
        raise NotImplementedError

    def detect_call(self, utterances: Sequence[Utterance]) -> ServiceDetection:
        """The services and the vehicle model the call names."""
        return ServiceDetection(self.detect(utterances), None)


def mentioned_vehicle_model(pricing: PricingSource, utterances: Sequence[Utterance]) -> str | None:
    """The price-list model named last in the call ("my Swift is making a
    noise"), matched as whole words; None when no model is named."""
    config = pricing_source(pricing)()
    models = [(model, f" {normalize_model(model)} ") for model in config.vehicle_models]
    if not models:
        return None
    for utterance in reversed(utterances):
        text = f" {normalize_model(utterance.transcript)} "
        named = [(model, key) for model, key in models if key in text]
        if named:
            # "Swift Dzire" rather than "Swift" when both match.
            return max(named, key=lambda item: len(item[1]))[0]
    return None


class KeywordServiceDetector(ServiceDetectionProvider):
    """Every service whose keyword is said anywhere in the call (English
    keywords; it cannot tell "the battery is fine" from a battery fault)."""

    def __init__(self, pricing: PricingSource) -> None:
        self._pricing = pricing_source(pricing)

    def detect(self, utterances: Sequence[Utterance]) -> list[str]:
        config = self._pricing()
        catalogue = [(name, config.keywords_for(name)) for name in config.service_names]
        found: list[str] = []
        for utterance in utterances:
            text = utterance.transcript.casefold()
            for name, keywords in catalogue:
                if name not in found and any(keyword.casefold() in text for keyword in keywords):
                    found.append(name)
        return found

    def detect_call(self, utterances: Sequence[Utterance]) -> ServiceDetection:
        return ServiceDetection(
            self.detect(utterances), mentioned_vehicle_model(self._pricing, utterances)
        )


class LLMServiceDetector(ServiceDetectionProvider):
    """Reads the conversation like a service advisor would: services the
    customer needs or asks for, or that the ICR agrees to do, in any of the
    supported languages; not ones that are declined or ruled out. Falls back
    to the keyword detector when the LLM fails."""

    def __init__(
        self,
        llm_client: LLMClient,
        pricing: PricingSource,
        fallback: ServiceDetectionProvider | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._pricing = pricing_source(pricing)
        self._fallback = fallback or KeywordServiceDetector(self._pricing)

    def detect(self, utterances: Sequence[Utterance]) -> list[str]:
        return self.detect_call(utterances).services

    def detect_call(self, utterances: Sequence[Utterance]) -> ServiceDetection:
        if not utterances:
            return ServiceDetection([], None)
        try:
            response = self._llm_client.complete(LLMRequest(prompt=self._prompt(utterances)))
            return self._parse(response.text or "")
        except Exception:
            logger.warning(
                "LLM service detection failed; using the price-list keywords.", exc_info=True
            )
            return self._fallback.detect_call(utterances)

    def _prompt(self, utterances: Sequence[Utterance]) -> str:
        config = self._pricing()
        catalogue = "\n".join(
            f'- "{name}" (e.g. {", ".join(config.keywords_for(name))})'
            for name in config.service_names
        )
        models = config.vehicle_models[:_MAX_MODELS_IN_PROMPT]
        model_section = (
            "Vehicle models on the price list: "
            + ", ".join(f'"{model}"' for model in models)
            + "\n\n"
            if models
            else ""
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
            f"{model_section}"
            f"Conversation:\n{transcript}\n\n"
            "Rules:\n"
            "- Include a service when the customer describes a problem it fixes, asks for "
            "it, or the ICR agrees or books to do it.\n"
            "- Do not include a service that is ruled out or declined (e.g. \"the battery "
            "is fine\", \"no need for an oil change\"), or only offered and not taken up.\n"
            "- Use only the exact service names from the price list; never invent one.\n"
            "- List them in the order they came up in the call.\n"
            "- vehicle_model: the customer's vehicle model if the call names it and it is "
            "one of the vehicle models listed above (exact name), else null.\n"
            'Reply with JSON only: {"services": ["<service name>", ...], '
            '"vehicle_model": "<model>" or null}'
        )

    def _parse(self, text: str) -> ServiceDetection:
        match = _JSON_OBJECT.search(text)
        if match is None:
            raise ValueError("The LLM reply holds no JSON object.")
        payload = json.loads(match.group(0))
        names = payload.get("services") if isinstance(payload, dict) else None
        if not isinstance(names, list):
            raise ValueError("The LLM reply has no services list.")
        config = self._pricing()
        known = {name.casefold(): name for name in config.service_names}
        found: list[str] = []
        for name in names:
            service = known.get(name.strip().casefold()) if isinstance(name, str) else None
            if service is not None and service not in found:
                found.append(service)
        model = payload.get("vehicle_model")
        vehicle_model = (
            config.match_vehicle_model(model) if isinstance(model, str) and model.strip() else None
        )
        return ServiceDetection(found, vehicle_model)
