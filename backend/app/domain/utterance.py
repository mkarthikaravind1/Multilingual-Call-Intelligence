from dataclasses import dataclass
from enum import Enum
from app.core.constants import SUPPORTED_LANGUAGES

class SpeakerRole(str, Enum):
    """
    Domain-level speaker roles relevant to this business.

    This is intentionally a SEPARATE enum from any AI-layer speaker role
    representation. The domain layer must not import from `app.ai.*` —
    even importing an enum from there would make this file depend on the
    AI module's existence. Translating an AI-layer role into this domain
    role is the job of the service/application layer that builds an
    Utterance, not this file.
    """
    ICR = "ICR"
    CUSTOMER = "CUSTOMER"
    # Extensible: a future role (e.g. SUPERVISOR) is added here as one
    # more enum member — nothing else in this file changes.


@dataclass(frozen=True)
class Utterance:
    """
    One meaningful spoken segment in a customer service conversation,
    combining transcript, speaker role, language, timing, and confidence
    into a single provider-independent fact.

    `frozen=True` makes instances immutable after creation — an Utterance
    represents something that already happened in the conversation; it
    shouldn't be mutated later by unrelated code. If a corrected version
    is needed, create a new Utterance rather than editing this one.
    """

    transcript: str
    speaker_role: SpeakerRole
    languages: tuple[str, ...]
    # Tuple of language codes present in this utterance, e.g. ("en",) for
    # a single-language segment or ("en", "ta") for mixed. Using the same
    # shape for both cases avoids a separate "mixed utterance" type.
    start_time: float
    end_time: float
    confidence: float | None = None

    def __post_init__(self) -> None:
        """
        Enforces domain invariants at construction time, so an invalid
        Utterance can never exist in the system — callers don't need to
        re-check these rules themselves.
        """
        if not self.transcript.strip():
            raise ValueError("Utterance transcript must not be empty.")

        if self.end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")

        if not self.languages:
            raise ValueError("Utterance must specify at least one language.")

        for lang in self.languages:
            if lang not in SUPPORTED_LANGUAGES:
                raise ValueError(
                    f"Unsupported language code: {lang!r}. "
                    f"Must be one of {SUPPORTED_LANGUAGES}."
                )

        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0.")

    @property
    def duration(self) -> float:
        """Length of the utterance in seconds, derived from timestamps."""
        return self.end_time - self.start_time

    @property
    def is_mixed_language(self) -> bool:
        """True when this utterance contains more than one language."""
        return len(self.languages) > 1