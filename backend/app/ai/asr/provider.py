from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class TimedText:
    text: str
    start_time: float
    end_time: float

@dataclass
class ASRResult:
    transcript: str
    detected_language: str
    start_time: float
    end_time: float
    confidence: float | None = None
    transcript: str
    detected_language: str
    start_time: float
    end_time: float
    confidence: float | None = None
    timed_text: tuple[TimedText, ...] = ()

class NoSpeechDetected(Exception):
    """The audio held no speech to transcribe (e.g. silence at the end of a
    call). Not a failure: there is simply nothing to add."""


class ASRProvider(ABC):
    # Whether transcribe() takes a language_hint. Providers without one are
    # only ever called with the audio.
    supports_language_hint: bool = False

    @abstractmethod
    def transcribe(self, audio: bytes, language_hint: str | None = None) -> ASRResult:
        """language_hint: the language the speech is known to be in (a
        SUPPORTED_LANGUAGES code), instead of detecting it from the audio."""
        raise NotImplementedError