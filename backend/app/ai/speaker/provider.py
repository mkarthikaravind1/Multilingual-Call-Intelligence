from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class SpeakerRole(str, Enum):
    """
    The known roles a diarized speaker can be assigned in this domain.
    Kept as a small closed set (not a free-form string) because the rest
    of the system (services, domain logic) needs to reason about exactly
    these two roles — a typo like "Customre" should fail loudly, not
    silently produce an unrecognized role string.
    """
    ICR = "ICR"
    CUSTOMER = "CUSTOMER"
    UNKNOWN = "UNKNOWN"
    # UNKNOWN exists because role identification may legitimately fail or
    # be unavailable for a segment — callers should handle that explicitly
    # rather than the system guessing or crashing.


@dataclass
class DiarizedSegment:
    """
    One contiguous stretch of audio attributed to a single anonymous
    speaker, with NO knowledge of who that speaker actually is (ICR or
    Customer). This is deliberately "dumb" — it only knows acoustic
    speaker turns, which is all a diarization model can know on its own.
    """
    speaker_id: str
    # Anonymous label like "speaker_1". Diarization models don't know
    # real-world roles — only that segments belong to the same voice.
    start_time: float
    end_time: float
    confidence: float | None = None


@dataclass
class SpeakerRoleAssignment:
    """
    Maps one anonymous speaker_id to a role, independent of any specific
    timestamp or segment. A single speaker_id keeps the same role for
    the whole call, so this is assigned once per speaker, not per segment.
    """
    speaker_id: str
    role: SpeakerRole
    confidence: float | None = None


@dataclass
class SpeakerSegment:
    """
    The COMBINED, provider-independent result: a diarized segment with
    its role already resolved. This is the shape downstream code (e.g.
    the future domain-level Utterance) actually wants to consume — it
    shouldn't need to separately look up role-per-speaker itself.

    This class is assembled by combining a DiarizedSegment with a
    SpeakerRoleAssignment; neither provider below returns this directly.
    """
    speaker_id: str
    role: SpeakerRole
    start_time: float
    end_time: float
    confidence: float | None = None


class DiarizationProvider(ABC):
    """
    Contract for "who spoke when." Implementations detect distinct voices
    in mixed audio and their time boundaries — nothing more.

    Deliberately has no method or field related to ICR/Customer roles:
    a diarization model (e.g. pyannote) has no way to know real-world
    roles, so asking this contract for roles would force every
    implementation to fake an answer it can't actually give.
    """

    @abstractmethod
    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        """
        Split mixed audio into per-speaker segments.
        `audio: bytes` mirrors the ASR contract — provider-neutral input,
        no assumption about file format, streaming, or SDK type.
        """
        raise NotImplementedError


class RoleIdentificationProvider(ABC):
    """
    Contract for "which anonymous speaker is ICR vs Customer."

    Takes diarization output as input rather than raw audio, because role
    identification is a reasoning step over already-detected speakers —
    it does not need to re-analyze the acoustic signal itself. This also
    means a role-identification implementation could be as simple as a
    rule ("first speaker = ICR") without ever touching audio directly.
    """

    @abstractmethod
    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        """
        Given diarized segments, return one role assignment per unique
        speaker_id found in `segments`.
        """
        raise NotImplementedError