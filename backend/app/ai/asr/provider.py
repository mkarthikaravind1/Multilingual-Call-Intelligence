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
    @abstractmethod
    def transcribe(self, audio: bytes) -> ASRResult:
        raise NotImplementedError