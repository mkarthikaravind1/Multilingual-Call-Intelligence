"""LLM escalation detection, used together with the rules (never instead of
them): it understands intent phrased in any supported language, and it can
only add signals to what the rules found."""

import json
import logging
import re
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
        signals = _grounded(self._parse(response.text), context)
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

    @staticmethod
    def task_instructions() -> str:
        """This provider's task inside a combined live-analysis request (see
        LLMLiveAnalysisProvider): the same signal types, levels and rules as
        assess()'s own prompt."""
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        return (
            f"Signal types: {_SIGNAL_TYPES}\n"
            f"Levels: {_SIGNAL_LEVELS}\n\n"
            f"Rules:\n{rules}\n\n"
            f'"escalation" is a JSON object in exactly this shape:\n{_RESPONSE_SHAPE}\n'
            'If the call is not escalating, "escalation" is {"signals": []}.'
        )

    def parse_signals(
        self, data: Any, context: EscalationContext
    ) -> tuple[EscalationSignal, ...] | None:
        """The signals in a decoded answer, checked as assess() checks them
        (including that each quote was said on the call); None when the
        answer is unusable."""
        try:
            return _grounded(self._signals(data), context)
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("Discarding invalid LLM escalation response: %s", exc)
            return None

    def _signals(self, data: Any) -> tuple[EscalationSignal, ...]:
        raw_signals = data["signals"]
        if not isinstance(raw_signals, list):
            raise TypeError("signals must be a list")
        return tuple(self._signal(item) for item in raw_signals)

    def _parse(self, text: str) -> tuple[EscalationSignal, ...]:
        try:
            return self._signals(json.loads(_strip_code_fence(text)))
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


# Quote fragments joined with an ellipsis are checked one by one.
_ELLIPSIS = re.compile(r"\.\.\.|…")
_SPEAKER_LABEL = re.compile(r"^\s*(customer|icr|unknown)\s*:", re.IGNORECASE)


def _words(text: str) -> str:
    """Lower-cased words and numbers only, single-spaced, any script."""
    return " ".join(re.findall(r"\w+", text.casefold()))


def _quoted_in(evidence: str, said: str) -> bool:
    fragments = [
        _words(_SPEAKER_LABEL.sub("", fragment)) for fragment in _ELLIPSIS.split(evidence)
    ]
    fragments = [fragment for fragment in fragments if fragment]
    return bool(fragments) and all(f" {fragment} " in said for fragment in fragments)


def _grounded(
    signals: tuple[EscalationSignal, ...], context: EscalationContext
) -> tuple[EscalationSignal, ...]:
    """Only signals whose evidence is words actually said on the call. A
    supervisor is alerted on these, and a model can invent a quote (a test
    call got a critical "manager request" from made-up Tamil text). Any
    speaker's words count: on mixed audio the customer's lines are
    sometimes labelled as the ICR's."""
    said = " " + " ".join(_words(u.transcript) for u in context.conversation.utterances) + " "
    kept = []
    for signal in signals:
        if signal.evidence and _quoted_in(signal.evidence, said):
            kept.append(signal)
        else:
            logger.warning(
                "Dropping LLM escalation signal %s for call %r: its evidence is not "
                "a quote from the call: %r",
                signal.signal_type.value,
                context.conversation.call_id,
                signal.evidence,
            )
    return tuple(kept)


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

    @property
    def llm(self) -> LLMEscalationProvider:
        return self._llm

    def assess(self, context: EscalationContext) -> EscalationAssessment:
        from_rules = self._rules.assess(context)
        try:
            from_llm = self._llm.assess(context)
        except Exception:
            logger.exception("LLM escalation detection failed; using the rules only")
            return from_rules
        return _with_llm(from_rules, from_llm.signals)

    def with_llm_signals(
        self, llm_signals: tuple[EscalationSignal, ...]
    ) -> EscalationDetectionProvider:
        """This provider with the LLM's signals already found (by a combined
        live-analysis request): the rules still run, the LLM is not asked."""
        return _GivenLLMSignals(self._rules, llm_signals)


class _GivenLLMSignals(EscalationDetectionProvider):
    def __init__(
        self, rules: RuleBasedEscalationProvider, llm_signals: tuple[EscalationSignal, ...]
    ) -> None:
        self._rules = rules
        self._llm_signals = llm_signals

    def assess(self, context: EscalationContext) -> EscalationAssessment:
        return _with_llm(self._rules.assess(context), self._llm_signals)


def _with_llm(
    from_rules: EscalationAssessment, llm_signals: tuple[EscalationSignal, ...]
) -> EscalationAssessment:
    signals = merge_signals(from_rules.signals, llm_signals)
    level = EscalationLevel.highest(
        from_rules.level, combined_level(llm_signals), combined_level(signals)
    )
    return EscalationAssessment(level=level, signals=signals)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()
