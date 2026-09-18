from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.constants import SUPPORTED_LANGUAGES

@dataclass
class LanguageSpan:
    language: str
    confidence: float | None = None


@dataclass
class LanguageIdentificationResult:
    languages: list[LanguageSpan]

    @property
    def is_mixed(self) -> bool:
        return len(self.languages) > 1


class LanguageIdentificationProvider(ABC):
    @abstractmethod
    def identify(self, text: str) -> LanguageIdentificationResult:
        raise NotImplementedError