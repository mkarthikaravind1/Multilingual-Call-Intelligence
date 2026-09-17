from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ASRResult:
    """
    Represents the outcome of a single transcription operation,
    independent of which provider produced it.

    Plain data holder — no behavior, no provider knowledge. Any ASR
    provider (Sarvam, AWS, or a future one) must be able to populate
    these same fields, even if their raw API responses look completely
    different internally.
    """

    transcript: str
    # The recognized text. Always present, even if empty (e.g. silence).

    detected_language: str
    # Language code detected/used for this transcription (e.g. "ta", "en").
    # Kept as a plain string — validating against SUPPORTED_LANGUAGES is a
    # business-layer concern, not this layer's job.

    start_time: float
    end_time: float
    # Timestamp boundaries (in seconds), relative to the start of the audio.
    # Needed later to align ASR output with speaker segments.

    confidence: float | None = None
    # ASR confidence score, when the provider makes one available.


class ASRProvider(ABC):
    """
    Abstract contract every ASR provider implementation must follow.

    Why an ABC: callers should be able to call `provider.transcribe(audio)`
    without knowing which vendor it is. The ABC enforces that every
    concrete provider implements the same method signature.

    Why no Sarvam/AWS knowledge here: if this class referenced a specific
    vendor's SDK, every provider would be forced to reshape around that
    vendor's assumptions — defeating the abstraction.

    Why speaker info is excluded: speaker identification is a separate
    capability with its own abstraction and possibly a different
    provider/model. Bundling it here would force every ASR provider to
    also handle speaker logic.
    """

    @abstractmethod
    def transcribe(self, audio: bytes) -> ASRResult:
        """
        Transcribe raw audio into text.

        `audio: bytes` instead of a file path or SDK-specific stream type
        keeps the signature provider-neutral, whether audio comes from a
        live call stream, an uploaded file, or a test fixture.

        Returns an ASRResult — never a provider-specific response object.
        """
        raise NotImplementedError