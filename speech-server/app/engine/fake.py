import asyncio
from typing import Optional
import numpy as np
from app.engine.base import BaseSTTEngine, Segment, TranscriptionResponse
from app.audio import is_silence


class FakeSTTEngine(BaseSTTEngine):
    """
    Deterministic mock STT engine for unit tests and lightweight verification.
    Requires no model download, no GPU, and zero network access.
    """

    def __init__(
        self,
        model_name: str = "fake-whisper-mock",
        device: str = "cpu",
        loaded: bool = True,
    ):
        self.model_name = model_name
        self.device = device
        self._loaded = loaded
        self.default_language = "ta"
        self.default_transcript = "வணக்கம் service checkup ready"

    def load(self) -> None:
        self._loaded = True

    def set_loaded(self, loaded: bool) -> None:
        self._loaded = loaded

    def is_loaded(self) -> bool:
        return self._loaded

    def get_info(self) -> dict:
        return {
            "model": self.model_name,
            "device": self.device,
        }

    async def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
        with_timestamps: bool = True,
    ) -> TranscriptionResponse:
        duration = float(len(audio)) / sample_rate

        # Check silence
        if is_silence(audio) or len(audio) == 0:
            return TranscriptionResponse(
                transcript="",
                language=language or self.default_language,
                confidence=None,
                duration=round(duration, 3),
                no_speech=True,
                segments=[],
            )

        lang = language if language in {"ta", "en", "te", "kn", "ml"} else self.default_language

        if lang == "en":
            text = "Welcome to the service centre"
        elif lang == "te":
            text = "నమస్కారం సర్వీస్ సెంటర్"
        elif lang == "kn":
            text = "ನಮಸ್ಕಾರ ಸರ್ವೀಸ್ ಸೆಂಟರ್"
        elif lang == "ml":
            text = "നമസ്കാരം സർവീസ് സെന്റർ"
        else:
            text = "வணக்கம் engine oil change service ready"

        segments = []
        if with_timestamps:
            mid = round(duration / 2.0, 2)
            dur = round(duration, 2)
            words = text.split()
            half = len(words) // 2
            segments = [
                Segment(text=" ".join(words[:half]) if half > 0 else text, start=0.0, end=mid),
                Segment(text=" ".join(words[half:]) if half > 0 else text, start=mid, end=dur),
            ]

        return TranscriptionResponse(
            transcript=text,
            language=lang,
            confidence=0.95,
            duration=round(duration, 3),
            no_speech=False,
            segments=segments,
        )

