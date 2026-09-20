from collections.abc import Sequence
from dataclasses import replace

from app.ai.speaker.provider import DiarizationProvider, DiarizedSegment


class ScriptedDiarizationProvider(DiarizationProvider):
    def __init__(self, segments: Sequence[DiarizedSegment]) -> None:
        for segment in segments:
            if not segment.speaker_id.strip():
                raise ValueError("speaker_id must not be empty.")
            if segment.end_time < segment.start_time:
                raise ValueError("end_time cannot be before start_time.")
        self._segments = sorted(
            (replace(segment) for segment in segments),
            key=lambda segment: segment.start_time,
        )

    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        return [replace(segment) for segment in self._segments]