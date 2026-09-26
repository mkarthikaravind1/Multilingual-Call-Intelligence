from dataclasses import dataclass
from enum import Enum
from app.core.constants import SUPPORTED_LANGUAGES

class SpeakerRole(str, Enum):
    ICR = "ICR"
    CUSTOMER = "CUSTOMER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Utterance:
    utterance_id: str
    transcript: str
    speaker_role: SpeakerRole
    languages: tuple[str, ...]
    start_time: float
    end_time: float
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.utterance_id.strip():
            raise ValueError("utterance_id must not be empty.")

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
        return self.end_time - self.start_time

    @property
    def is_mixed_language(self) -> bool:
        return len(self.languages) > 1