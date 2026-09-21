from collections.abc import Sequence
from dataclasses import dataclass

from app.ai.asr.provider import TimedText
from app.ai.speaker.provider import DiarizedSegment


@dataclass(frozen=True)
class SpeakerTurn:
    speaker_id: str
    text: str
    start_time: float
    end_time: float


def align_timed_text_to_speakers(
    timed_text: Sequence[TimedText], segments: Sequence[DiarizedSegment]
) -> tuple[SpeakerTurn, ...]:
    speaker_intervals = _merged_intervals_by_speaker(segments)
    turns: list[SpeakerTurn] = []

    for item in sorted(timed_text, key=lambda i: (i.start_time, i.end_time)):
        speaker_id = _dominant_speaker(item, speaker_intervals)
        if speaker_id is None:
            continue
        if turns and turns[-1].speaker_id == speaker_id:
            last = turns[-1]
            turns[-1] = SpeakerTurn(
                speaker_id=speaker_id,
                text=f"{last.text} {item.text}",
                start_time=last.start_time,
                end_time=max(last.end_time, item.end_time),
            )
        else:
            turns.append(
                SpeakerTurn(speaker_id, item.text, item.start_time, item.end_time)
            )

    return tuple(turns)


def _merged_intervals_by_speaker(
    segments: Sequence[DiarizedSegment],
) -> dict[str, list[tuple[float, float]]]:
    merged: dict[str, list[tuple[float, float]]] = {}
    for segment in sorted(segments, key=lambda s: s.start_time):
        if segment.end_time <= segment.start_time:
            continue
        intervals = merged.setdefault(segment.speaker_id, [])
        if intervals and segment.start_time <= intervals[-1][1]:
            intervals[-1] = (
                intervals[-1][0],
                max(intervals[-1][1], segment.end_time),
            )
        else:
            intervals.append((segment.start_time, segment.end_time))
    return merged


def _dominant_speaker(
    item: TimedText, speaker_intervals: dict[str, list[tuple[float, float]]]
) -> str | None:
    best_speaker: str | None = None
    best_overlap = 0.0
    for speaker_id, intervals in speaker_intervals.items():
        overlap = sum(
            max(0.0, min(end, item.end_time) - max(start, item.start_time))
            for start, end in intervals
        )
        if overlap > best_overlap:
            best_speaker, best_overlap = speaker_id, overlap
    return best_speaker