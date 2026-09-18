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


class DiarizationProvider(ABC):
    @abstractmethod
    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        raise NotImplementedError


class RoleIdentificationProvider(ABC):
    @abstractmethod
    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:

        raise NotImplementedError