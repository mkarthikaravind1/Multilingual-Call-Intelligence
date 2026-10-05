from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

class SpeakerRole(str, Enum):
    ICR = "ICR"
    CUSTOMER = "CUSTOMER"
    UNKNOWN = "UNKNOWN"

@dataclass
class DiarizedSegment:
    speaker_id: str
    start_time: float
    end_time: float
    confidence: float | None = None
    # The speaker's voice embedding (the same for all of a speaker's
    # segments in one diarization), when the provider computes one. Lets a
    # speaker be recognised again in later audio of the same call.
    embedding: tuple[float, ...] | None = None


@dataclass
class SpeakerRoleAssignment:
    speaker_id: str
    role: SpeakerRole
    confidence: float | None = None


@dataclass
class SpeakerSegment:
    speaker_id: str
    role: SpeakerRole
    start_time: float
    end_time: float
    confidence: float | None = None


class DiarizationError(RuntimeError):
    pass


class DiarizationProvider(ABC):
    @abstractmethod
    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        raise NotImplementedError

    def warm_up(self) -> None:
        """Load any models ahead of the first call. Nothing to load by default."""


class RoleIdentificationProvider(ABC):
    @abstractmethod
    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:

        raise NotImplementedError

    def observe_speech(
        self, speaker_id: str, transcript: str, *, role: SpeakerRole | None = None
    ) -> SpeakerRole | None:
        """Called with what a speaker (as named in the latest identify_roles
        segments, or a call's track) said. role is given when it is already
        known. Returns the speaker's role if it is now known, else None.
        Providers that do not learn from speech ignore it."""
        return None