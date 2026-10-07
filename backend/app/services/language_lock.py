from collections.abc import Hashable
from dataclasses import dataclass

from app.core.languages import INDIC_LANGUAGES


@dataclass
class _SpeakerLanguage:
    candidate: str | None = None
    streak: int = 0
    locked: str | None = None
    misses: int = 0


class LanguageLock:
    """Learns the Indian language each speaker of a call talks in, so the
    ASR can be told it instead of guessing it again from every few seconds
    of audio (where short chunks are often misheard as another language).

    A speaker (a call track, or None for mixed audio) is locked to a
    language after lock_after chunks in a row are heard in it. English
    chunks neither lock nor break the run: speakers who mix English into
    Tamil stay Tamil, and the ASR's code-mix mode keeps the English words.
    Speech that still comes out empty or in another language unlock_after
    times in a row releases the lock, and detection starts afresh.
    lock_after=0 turns locking off.
    """

    def __init__(self, lock_after: int = 2, unlock_after: int = 2) -> None:
        if lock_after < 0 or unlock_after < 1:
            raise ValueError("lock_after must be >= 0 and unlock_after >= 1.")
        self._lock_after = lock_after
        self._unlock_after = unlock_after
        self._speakers: dict[Hashable, _SpeakerLanguage] = {}

    def hint(self, speaker: Hashable) -> str | None:
        state = self._speakers.get(speaker)
        return None if state is None else state.locked

    def observe(self, speaker: Hashable, language: str) -> None:
        """A chunk of the speaker's audio was transcribed as language."""
        if not self._lock_after:
            return
        state = self._speakers.setdefault(speaker, _SpeakerLanguage())
        if state.locked is not None:
            if language in INDIC_LANGUAGES and language != state.locked:
                self._miss(speaker, state)
            else:
                state.misses = 0
            return
        if language not in INDIC_LANGUAGES:
            return
        if language == state.candidate:
            state.streak += 1
        else:
            state.candidate, state.streak = language, 1
        if state.streak >= self._lock_after:
            state.locked = language

    def observe_no_speech(self, speaker: Hashable) -> None:
        """The speaker's audio came back without any speech."""
        state = self._speakers.get(speaker)
        if state is not None and state.locked is not None:
            self._miss(speaker, state)

    def _miss(self, speaker: Hashable, state: _SpeakerLanguage) -> None:
        state.misses += 1
        if state.misses >= self._unlock_after:
            self._speakers[speaker] = _SpeakerLanguage()
