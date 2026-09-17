from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.constants import SUPPORTED_LANGUAGES


@dataclass
class LanguageSpan:
    """
    One language detected within a segment, with how confident the
    detector is about it. A plain (language, confidence) pair — no
    behavior, no provider knowledge.
    """
    language: str
    # Expected to be one of SUPPORTED_LANGUAGES. Not enforced here with a
    # hard validation check — that would make this data model responsible
    # for business-rule enforcement, which belongs to the service/domain
    # layer that actually receives and acts on this result.
    confidence: float | None = None


@dataclass
class LanguageIdentificationResult:
    """
    Provider-independent result of identifying language(s) within a
    single transcript segment.

    Deliberately holds a LIST of LanguageSpan rather than one language
    string, so a single-language segment and a mixed-language segment
    use the exact same shape — no separate "mixed result" type needed.
    """
    languages: list[LanguageSpan]

    @property
    def is_mixed(self) -> bool:
        """
        True when more than one language was detected in this segment.
        Derived from `languages` rather than stored as a separate field,
        so it can never be set inconsistently with the actual data.
        """
        return len(self.languages) > 1


class LanguageIdentificationProvider(ABC):
    """
    Contract for identifying the language(s) present in a transcript
    segment (e.g. one ASR utterance).

    Why separate from ASR: ASR's job is producing text from audio;
    language identification's job is reasoning about that text. Some
    ASR engines guess a language internally, but that guess is often
    unreliable for code-switched speech — keeping this as its own
    contract means it can be improved or replaced independently of
    whichever ASR provider is in use, and can even combine signals from
    multiple ASR outputs if needed later.

    Why this takes text, not audio: mixed-language detection (e.g.
    Tamil-English code-switching within one sentence) is naturally a
    text-level problem once transcription exists. This keeps audio
    handling entirely inside the ASR module, avoiding duplicated
    responsibility across two AI modules.
    """

    @abstractmethod
    def identify(self, text: str) -> LanguageIdentificationResult:
        """
        Identify the language(s) present in a single transcript segment.

        `text: str` is the ASR output for one segment/utterance — not
        raw audio, and not the full call transcript, so results stay at
        the segment level as required.
        """
        raise NotImplementedError