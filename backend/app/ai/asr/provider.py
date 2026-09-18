from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ASRResult:
    transcript: str
    detected_language: str
    start_time: float
    end_time: float
    confidence: float | None = None

class ASRProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: bytes) -> ASRResult:
        raise NotImplementedError