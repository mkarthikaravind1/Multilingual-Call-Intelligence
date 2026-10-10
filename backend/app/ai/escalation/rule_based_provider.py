"""Explainable escalation rules over the transcript and the call's analysis.

Phrase rules read only what the customer said (and speech whose speaker is
unknown), never the ICR. English patterns also catch English words used in
code-mixed speech. The native-script entries are common loanwords (manager,
court, refund, ...) as they are usually spelt in Tamil, Telugu, Kannada and
Malayalam; they should be reviewed by native speakers and are the place to
extend coverage. The optional LLM detector handles phrasing these miss.
"""

import re
from dataclasses import dataclass

from app.ai.escalation.provider import EscalationContext, EscalationDetectionProvider
from app.ai.sentiment.provider import SentimentLabel
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.escalation import (
    EscalationAssessment,
    EscalationLevel,
    EscalationSignal,
    EscalationSignalType,
)
from app.domain.utterance import SpeakerRole

NEGATIVE_TONE_MIN_CONFIDENCE = 0.75
OPEN_COMPLAINTS_FOR_WATCH = 2
_MAX_EVIDENCE = 200

_OPEN_STATUSES = frozenset({ComplaintCoverageStatus.DETECTED, ComplaintCoverageStatus.PROBED})
_CUSTOMER_ROLES = frozenset({SpeakerRole.CUSTOMER, SpeakerRole.UNKNOWN})


@dataclass(frozen=True)
class _PhraseRule:
    signal_type: EscalationSignalType
    level: EscalationLevel
    description: str
    english: re.Pattern[str]
    native_words: tuple[str, ...]

    def matches(self, text: str) -> bool:
        return bool(self.english.search(text)) or any(
            word in text for word in self.native_words
        )


def _words(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_PHRASE_RULES = (
    _PhraseRule(
        EscalationSignalType.LEGAL_THREAT,
        EscalationLevel.CRITICAL,
        "Customer mentioned legal action, a consumer court or the police.",
        _words(
            r"\b(consumer\s+(court|forum)|court|lawyer|advocate|legal\s+(action|notice)"
            r"|sue|suing|police|file\s+a\s+case)\b"
        ),
        (
            "நீதிமன்றம்", "கோர்ட்", "வக்கீல்", "போலீஸ்", "கன்ஸ்யூமர்",  # Tamil
            "కోర్టు", "లాయర్", "పోలీస్", "కన్స్యూమర్",  # Telugu
            "ಕೋರ್ಟ್", "ಲಾಯರ್", "ಪೊಲೀಸ್", "ಕನ್ಸ್ಯೂಮರ್",  # Kannada
            "കോടതി", "കോർട്ട്", "വക്കീൽ", "പോലീസ്", "കൺസ്യൂമർ",  # Malayalam
        ),
    ),
    _PhraseRule(
        EscalationSignalType.MANAGER_REQUEST,
        EscalationLevel.HIGH,
        "Customer asked for a manager or someone senior.",
        _words(
            r"\b((talk|speak|connect|transfer|put\s+me\s+through|want|need|get|call"
            r"|give|bring|where\s+is)\b.{0,30}"
            r"\b(manager|supervisor|senior|boss|higher\s+authority))\b"
            r"|\bescalat(e|ing|ion)\b"
        ),
        (
            "மேனேஜர்", "மேலாளர்",  # Tamil
            "మేనేజర్",  # Telugu
            "ಮ್ಯಾನೇಜರ್",  # Kannada
            "മാനേജർ",  # Malayalam
        ),
    ),
    _PhraseRule(
        EscalationSignalType.PUBLIC_COMPLAINT,
        EscalationLevel.HIGH,
        "Customer threatened to complain publicly (social media, reviews, press).",
        _words(
            r"\b(social\s+media|twitter|facebook|instagram|youtube|google\s+review"
            r"|post\s+(it|this|about\s+it)\s+online|go\s+viral|newspaper|news\s+channel)\b"
        ),
        ("சோஷியல் மீடியா", "யூடியூப்", "ఫేస్‌బుక్", "ಫೇಸ್‌ಬುಕ್", "ഫേസ്ബുക്ക്"),
    ),
    _PhraseRule(
        EscalationSignalType.CANCELLATION,
        EscalationLevel.HIGH,
        "Customer wants to cancel, get a refund or take their business elsewhere.",
        _words(
            r"\b(cancel|refund|money\s+back|take\s+my\s+(car|vehicle|business)\s+elsewhere"
            r"|never\s+(come|coming)\s+back|switch\s+to\s+another)\b"
        ),
        (
            "கேன்சல்", "ரீஃபண்ட்", "ரிஃபண்ட்",  # Tamil
            "క్యాన్సల్", "రీఫండ్",  # Telugu
            "ಕ್ಯಾನ್ಸಲ್", "ರೀಫಂಡ್",  # Kannada
            "ക്യാൻസൽ", "റീഫണ്ട്",  # Malayalam
        ),
    ),
)


def _evidence(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_EVIDENCE else text[: _MAX_EVIDENCE - 1] + "…"


# What the customer said or threatened, as opposed to how the call is going
# (tone, open complaints), which nearly every complaint call shows.
SERIOUS_SIGNAL_TYPES = frozenset(
    {
        EscalationSignalType.MANAGER_REQUEST,
        EscalationSignalType.LEGAL_THREAT,
        EscalationSignalType.PUBLIC_COMPLAINT,
        EscalationSignalType.CANCELLATION,
    }
)


def combined_level(signals: tuple[EscalationSignal, ...]) -> EscalationLevel:
    """Several concerns together weigh more than any one alone: two or more
    kinds of signal step the level up by one (at most to critical), but only
    when one of them is serious. A negative tone with open complaints alone
    stays at watch, or every complaint call would be high."""
    if not signals:
        return EscalationLevel.NONE
    level = EscalationLevel.highest(*(signal.level for signal in signals))
    types = {signal.signal_type for signal in signals}
    if len(types) < 2 or not types & SERIOUS_SIGNAL_TYPES:
        return level
    return _ONE_STEP_UP[level]


_ONE_STEP_UP = {
    EscalationLevel.WATCH: EscalationLevel.HIGH,
    EscalationLevel.HIGH: EscalationLevel.CRITICAL,
    EscalationLevel.CRITICAL: EscalationLevel.CRITICAL,
}


class RuleBasedEscalationProvider(EscalationDetectionProvider):
    def assess(self, context: EscalationContext) -> EscalationAssessment:
        signals = [
            *self._phrase_signals(context),
            *self._tone_signals(context),
            *self._complaint_signals(context),
        ]
        signal_tuple = tuple(signals)
        return EscalationAssessment(level=combined_level(signal_tuple), signals=signal_tuple)

    @staticmethod
    def _phrase_signals(context: EscalationContext) -> list[EscalationSignal]:
        found: list[EscalationSignal] = []
        for rule in _PHRASE_RULES:
            for utterance in context.conversation.utterances:
                if utterance.speaker_role in _CUSTOMER_ROLES and rule.matches(
                    utterance.transcript
                ):
                    found.append(
                        EscalationSignal(
                            signal_type=rule.signal_type,
                            level=rule.level,
                            description=rule.description,
                            evidence=_evidence(utterance.transcript),
                        )
                    )
                    break  # the first time the customer said it is enough
        return found

    @staticmethod
    def _tone_signals(context: EscalationContext) -> list[EscalationSignal]:
        sentiment = context.sentiment
        if (
            sentiment is None
            or not sentiment.label.is_negative
            or sentiment.confidence < NEGATIVE_TONE_MIN_CONFIDENCE
        ):
            return []
        return [
            EscalationSignal(
                signal_type=EscalationSignalType.NEGATIVE_TONE,
                level=EscalationLevel.WATCH,
                description=(
                    f"Customer's tone is clearly {sentiment.label.value.lower()} "
                    f"({round(sentiment.confidence * 100)}% confidence)."
                ),
                evidence=_evidence(sentiment.evidence),
            )
        ]

    @staticmethod
    def _complaint_signals(context: EscalationContext) -> list[EscalationSignal]:
        complaints = context.coverage.complaints
        unresolved = [c.category for c in complaints if c.status is ComplaintCoverageStatus.UNRESOLVED]
        open_ = [c.category for c in complaints if c.status in _OPEN_STATUSES]
        if unresolved:
            description = f"Complaint marked unresolved: {', '.join(unresolved)}."
        elif len(open_) >= OPEN_COMPLAINTS_FOR_WATCH:
            description = f"{len(open_)} complaints still open: {', '.join(open_)}."
        else:
            return []
        return [
            EscalationSignal(
                signal_type=EscalationSignalType.UNRESOLVED_COMPLAINTS,
                level=EscalationLevel.WATCH,
                description=description,
            )
        ]
