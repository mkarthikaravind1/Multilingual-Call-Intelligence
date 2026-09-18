from dataclasses import dataclass
from enum import Enum
from app.core.constants import SUPPORTED_LANGUAGES

class SpeakerRole(str, Enum):
    ICR = "ICR"
    CUSTOMER = "CUSTOMER"
    # Extensible: a future role (e.g. SUPERVISOR) is added here as one
    # more enum member — nothing else in this file changes.


@dataclass(frozen=True)
class Utterance:
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