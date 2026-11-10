from abc import ABC, abstractmethod
from typing import List, Optional
import numpy as np
from pydantic import BaseModel, Field


class Segment(BaseModel):
    text: str
    start: float
    end: float


class TranscriptionResponse(BaseModel):
    transcript: str
    language: str
    confidence: Optional[float] = Field(default=None)
    duration: float
    no_speech: bool = False
    segments: List[Segment] = Field(default_factory=list)


class BaseSTTEngine(ABC):
    """Abstract base class for Speech-To-Text engines."""

    @abstractmethod
    def load(self) -> None:
        """Loads model weights onto device."""
        pass

    @abstractmethod
    def is_loaded(self) -> bool:
        """Returns True if the model is ready to serve requests."""
        pass

    @abstractmethod
    def get_info(self) -> dict:
        """Returns model name and active device ('cuda' | 'cpu')."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
        with_timestamps: bool = True,
    ) -> TranscriptionResponse:
        """Transcribes 16kHz mono float32 audio."""
        pass

