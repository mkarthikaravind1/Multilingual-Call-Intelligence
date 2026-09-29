"""LLM escalation detection, used together with the rules (never instead of
them): it understands intent phrased in any supported language, and it can
only add signals to what the rules found."""

import json
import logging
from typing import Any

from app.ai.escalation.provider import EscalationContext, EscalationDetectionProvider
from app.ai.escalation.rule_based_provider import (
    RuleBasedEscalationProvider,
    combined_level,
)
from app.ai.llm.client import LLMClient, LLMRequest
from app.domain.escalation import (
    EscalationAssessment,
    EscalationLevel,
    EscalationSignal,
    EscalationSignalType,
    merge_signals,
)

logger = logging.getLogger(__name__)

_SIGNAL_TYPES = ", ".join(t.value for t in EscalationSignalType)
_SIGNAL_LEVELS = ", ".join(
    level.value for level in EscalationLevel if level is not EscalationLevel.NONE
)

_GUARDRAILS = (
    "Judge only what the customer says; ignore what the ICR says.",
    "Report a signal only when the conversation clearly supports it; do not invent.",
    "Use critical only for threats of legal action, a consumer court or the police.",
    "Use high for demands for a manager, threats to complain publicly, or to cancel or ask for a refund.",
    "Use watch for frustration or unresolved problems that are not yet a demand or threat.",
    "evidence must quote the customer's words from the conversation, in the original language.",
    "description must be one short English sentence a supervisor can act on.",
)

_RESPONSE_SHAPE = (
    '{"signals": [{"type": "<one of the types>", "level": "<watch | high | critical>", '
    '"description": "<short English sentence>", "evidence": "<customer quote>"}]}'
)


class LLMEscalationProvider(EscalationDetectionProvider):
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def assess(self, context: EscalationContext) -> EscalationAssessment:
        if not context.conversation.utterances:
            return EscalationAssessment(EscalationLevel.NONE)
        response = self._llm_client.complete(self._build_request(context))
        signals = self._parse(response.text)
        return EscalationAssessment(level=combined_level(signals), signals=signals)

    @staticmethod
    def _build_request(context: EscalationContext) -> LLMRequest:
        transcript = "\n".join(
            f"{u.speaker_role.value}: {u.transcript.strip()}"
            for u in context.conversation.utterances
        )
        complaints = (
            ", ".join(f"{c.category} ({c.status.value})" for c in context.coverage.complaints)
            or "none"
        )
        tone = (
            f"{context.sentiment.label.value} ({context.sentiment.confidence:.2f})"
            if context.sentiment is not None
            else "unknown"
        )
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        prompt = (
            "You watch a live automotive service call between an ICR (customer service "
            "representative) and a customer, and flag signs that the call is escalating "
            "and needs a supervisor. The conversation may be in Tamil, Telugu, Kannada, "
            "Malayalam, English or a mix.\n\n"
            f"Conversation:\n{transcript}\n\n"
            f"Complaints so far: {complaints}\n"
            f"Customer tone: {tone}\n\n"
            f"Signal types: {_SIGNAL_TYPES}\n"
            f"Levels: {_SIGNAL_LEVELS}\n\n"
            f"Rules:\n{rules}\n\n"
            "Respond with ONLY a single JSON object and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{_RESPONSE_SHAPE}\n"
            'If the call is not escalating, respond with exactly: {"signals": []}'
        )
        return LLMRequest(prompt=prompt)

    def _parse(self, text: str) -> tuple[EscalationSignal, ...]:
        try:
            data = json.loads(_strip_code_fence(text))
            raw_signals = data["signals"]
            if not isinstance(raw_signals, list):
                raise TypeError("signals must be a list")
            return tuple(self._signal(item) for item in raw_signals)
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("Discarding invalid LLM escalation response: %s", exc)
            return ()

    @staticmethod
    def _signal(item: Any) -> EscalationSignal:
        if not isinstance(item, dict):
            raise TypeError("each signal must be an object")
        evidence = item.get("evidence")
        return EscalationSignal(
            signal_type=EscalationSignalType(item["type"]),
            level=EscalationLevel(item["level"]),
            description=str(item["description"]).strip(),
            evidence=evidence.strip() if isinstance(evidence, str) and evidence.strip() else None,
        )


class HybridEscalationProvider(EscalationDetectionProvider):
    """Rules always run; the LLM adds what they miss. If the LLM fails, the
    rules' assessment stands."""

    def __init__(
        self,
        rules: RuleBasedEscalationProvider,
        llm: LLMEscalationProvider,
    ) -> None:
        self._rules = rules
        self._llm = llm

    def assess(self, context: EscalationContext) -> EscalationAssessment:
        from_rules = self._rules.assess(context)
        try:
            from_llm = self._llm.assess(context)
        except Exception:
            logger.exception("LLM escalation detection failed; using the rules only")
            return from_rules
        signals = merge_signals(from_rules.signals, from_llm.signals)
        level = EscalationLevel.highest(
            from_rules.level, from_llm.level, combined_level(signals)
        )
        return EscalationAssessment(level=level, signals=signals)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()
