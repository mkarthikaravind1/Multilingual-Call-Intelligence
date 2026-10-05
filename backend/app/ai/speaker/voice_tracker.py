"""Recognises a call's speakers again from one chunk of live audio to the
next.

Live audio is diarized one chunk at a time, and the diarizer's labels
(SPEAKER_00, SPEAKER_01, ...) only mean something within that chunk: the
same person can be SPEAKER_00 in one chunk and SPEAKER_01 in the next. The
tracker keeps a voice profile (the mean voice embedding) for each speaker of
the call and maps every chunk's labels onto stable call-wide ids
(speaker_1, speaker_2, ...) by voice similarity.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.ai.speaker.provider import DiarizedSegment

# A profile's mean follows the voice through the call, but one chunk never
# moves it by more than 1/_MAX_PROFILE_WEIGHT.
_MAX_PROFILE_WEIGHT = 20
# A voice print from a short fragment (the tail of a sentence cut by a chunk
# boundary) is unreliable: it may only join a speaker it clearly matches,
# never start a new one or reshape a profile.
MIN_NEW_SPEAKER_SECONDS = 1.5
MIN_UPDATE_SECONDS = 1.0
# Once every speaker of the call is known, a voice is given to the nearest
# one only when it is at least this alike; otherwise it stays unrecognised
# (UNKNOWN) rather than being forced onto the wrong person.
_MIN_FORCED_SIMILARITY = 0.25


@dataclass
class _VoiceProfile:
    speaker_id: str
    centroid: list[float]
    weight: int = 1


class VoiceTracker:
    def __init__(self, match_threshold: float = 0.45, max_speakers: int = 2) -> None:
        if max_speakers < 1:
            raise ValueError("max_speakers must be at least 1.")
        self._match_threshold = match_threshold
        self._max_speakers = max_speakers
        self._profiles: list[_VoiceProfile] = []

    @property
    def speaker_ids(self) -> tuple[str, ...]:
        return tuple(profile.speaker_id for profile in self._profiles)

    def match(self, segments: Sequence[DiarizedSegment]) -> dict[str, str]:
        """Map the chunk's speaker labels to call-wide speaker ids. A label
        without a voice embedding is left out (it cannot be recognised)."""
        embeddings: dict[str, tuple[float, ...]] = {}
        speaking_time: dict[str, float] = {}
        for segment in segments:
            speaking_time[segment.speaker_id] = speaking_time.get(segment.speaker_id, 0.0) + (
                segment.end_time - segment.start_time
            )
            if segment.embedding:
                embeddings.setdefault(segment.speaker_id, segment.embedding)

        mapping: dict[str, str] = {}
        taken: set[str] = set()
        # The speaker heard longest has the most reliable embedding: first.
        for label in sorted(embeddings, key=lambda label: -speaking_time[label]):
            vector = _normalised(embeddings[label])
            if vector is None:
                continue
            seconds = speaking_time[label]
            profile, is_new = self._best_match(vector, taken, seconds)
            if profile is None:
                continue  # not recognisable from this little speech
            if is_new:
                self._profiles.append(profile)
            elif seconds >= MIN_UPDATE_SECONDS:
                self._update(profile, vector)
            taken.add(profile.speaker_id)
            mapping[label] = profile.speaker_id
        return mapping

    def _best_match(
        self, vector: list[float], taken: set[str], seconds: float
    ) -> tuple[_VoiceProfile | None, bool]:
        """(profile, is_new): the speaker this voice is, a new speaker, or
        (None, False) when it cannot be told."""
        long_enough = seconds >= MIN_NEW_SPEAKER_SECONDS
        room = len(self._profiles) < self._max_speakers
        candidates = [p for p in self._profiles if p.speaker_id not in taken]
        if not candidates and not room:
            # More voices in this chunk than the call can have: two of the
            # chunk's labels are the same person (or crosstalk).
            candidates = list(self._profiles)
        if candidates:
            best = max(candidates, key=lambda p: _cosine(p.centroid, vector))
            similarity = _cosine(best.centroid, vector)
            if similarity >= self._match_threshold:
                return best, False
            if not room:
                # Every speaker of the call is known: the nearest one, if alike.
                if long_enough and similarity >= _MIN_FORCED_SIMILARITY:
                    return best, False
                return None, False
        if room and long_enough:
            return _VoiceProfile(f"speaker_{len(self._profiles) + 1}", list(vector)), True
        return None, False

    @staticmethod
    def _update(profile: _VoiceProfile, vector: list[float]) -> None:
        weight = min(profile.weight, _MAX_PROFILE_WEIGHT)
        merged = [(c * weight + v) / (weight + 1) for c, v in zip(profile.centroid, vector)]
        profile.centroid = _normalised(merged) or profile.centroid
        profile.weight += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "profiles": [
                {"speaker_id": p.speaker_id, "centroid": p.centroid, "weight": p.weight}
                for p in self._profiles
            ]
        }

    def load(self, data: Mapping[str, Any] | None) -> None:
        profiles: list[_VoiceProfile] = []
        for raw in (data or {}).get("profiles", []):
            try:
                profiles.append(
                    _VoiceProfile(
                        speaker_id=str(raw["speaker_id"]),
                        centroid=[float(v) for v in raw["centroid"]],
                        weight=int(raw.get("weight", 1)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self._profiles = profiles


def _normalised(vector: Sequence[float]) -> list[float] | None:
    norm = math.sqrt(sum(v * v for v in vector))
    if not norm or not math.isfinite(norm):
        return None
    return [v / norm for v in vector]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # Both are kept normalised.
    return sum(x * y for x, y in zip(a, b))
