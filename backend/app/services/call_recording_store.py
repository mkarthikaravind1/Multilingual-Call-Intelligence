import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class CallRecording:
    """A call's live audio, kept for transcribing again after the call:
    16-bit mono PCM per track (None: one mixed stream). Each track's audio
    starts at call time 0, as the live chunks' times do."""

    sample_rate: int
    max_seconds: float
    tracks: dict[str | None, bytearray] = field(default_factory=dict)
    truncated: bool = False

    def append(self, track: str | None, pcm: bytes) -> None:
        audio = self.tracks.setdefault(track, bytearray())
        room = int(self.max_seconds * self.sample_rate) * 2 - len(audio)
        if room < len(pcm):
            self.truncated = True
            pcm = pcm[: max(room, 0)]
        audio.extend(pcm)

    def duration(self, track: str | None) -> float:
        return len(self.tracks.get(track, b"")) / (2 * self.sample_rate)


class CallRecordingStore:
    """Holds finished calls' recordings in memory until post-call processing
    takes them (or they expire). Recordings are large (about 2 MB a minute
    per track at 16 kHz), so only the newest max_calls are kept.

    One instance only: a recording is on the API instance that served the
    call's media stream. When post-call processing runs elsewhere, it finds
    none and keeps the live transcript."""

    def __init__(
        self,
        max_calls: int = 20,
        ttl_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_calls = max_calls
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._recordings: OrderedDict[str, tuple[float, CallRecording]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, call_id: str, recording: CallRecording) -> None:
        with self._lock:
            self._expire()
            self._recordings.pop(call_id, None)
            self._recordings[call_id] = (self._clock(), recording)
            while len(self._recordings) > self._max_calls:
                self._recordings.popitem(last=False)

    def take(self, call_id: str) -> CallRecording | None:
        with self._lock:
            self._expire()
            entry = self._recordings.pop(call_id, None)
        return None if entry is None else entry[1]

    def _expire(self) -> None:
        deadline = self._clock() - self._ttl_seconds
        while self._recordings:
            stored_at, _ = next(iter(self._recordings.values()))
            if stored_at >= deadline:
                return
            self._recordings.popitem(last=False)
