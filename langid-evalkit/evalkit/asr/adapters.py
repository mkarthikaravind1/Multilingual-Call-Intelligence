"""ASR Service Adapter Interface and Implementations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import mimetypes
import os
import time
from typing import Any, Dict, List, Optional
import httpx


@dataclass
class ASRResponse:
    transcript: str
    language: str
    confidence: Optional[float] = None
    duration: float = 0.0
    no_speech: bool = False
    segments: List[Dict[str, Any]] = field(default_factory=list)


class BaseASRAdapter(ABC):
    """Abstract base adapter for speech-to-text engines."""

    @abstractmethod
    def transcribe(self, audio_path: str, language: Optional[str] = None) -> ASRResponse:
        """Transcribe an audio file.

        Args:
            audio_path: Absolute or relative path to WAV/audio file.
            language: Optional language hint ('ta', 'en', 'te', 'kn', 'ml').

        Returns:
            ASRResponse containing transcript and metadata.
        """
        pass


class HTTPASRAdapter(BaseASRAdapter):
    """Standard HTTP Adapter talking to POST <url>/v1/transcribe."""

    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.endpoint = f"{self.base_url}/v1/transcribe"

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> ASRResponse:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        mime_type, _ = mimetypes.guess_type(audio_path)
        mime_type = mime_type or "audio/wav"
        filename = os.path.basename(audio_path)

        data = {}
        if language:
            data["language"] = language

        with open(audio_path, "rb") as f:
            files = {"file": (filename, f, mime_type)}
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.endpoint, data=data, files=files)
                resp.raise_for_status()
                payload = resp.json()

        return ASRResponse(
            transcript=payload.get("transcript", ""),
            language=payload.get("language", language or ""),
            confidence=payload.get("confidence"),
            duration=float(payload.get("duration", 0.0)),
            no_speech=bool(payload.get("no_speech", False)),
            segments=payload.get("segments", []),
        )


class MockASRAdapter(BaseASRAdapter):
    """Mock ASR Adapter for testing and offline validation without running servers."""

    def __init__(self, canned_responses: Optional[Dict[str, str]] = None, simulated_latency: float = 0.05):
        self.canned_responses = canned_responses or {}
        self.simulated_latency = simulated_latency

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> ASRResponse:
        filename = os.path.basename(audio_path)
        transcript = self.canned_responses.get(filename, "வணக்கம் உங்கள் சர்வீஸ் முடிந்தது")
        if self.simulated_latency > 0:
            time.sleep(self.simulated_latency)
        return ASRResponse(
            transcript=transcript,
            language=language or "ta",
            confidence=0.98,
            duration=2.5,
            no_speech=False,
            segments=[{"text": transcript, "start": 0.0, "end": 2.5}],
        )

