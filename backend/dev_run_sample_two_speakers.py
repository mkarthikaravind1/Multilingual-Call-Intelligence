import sys
from collections.abc import Sequence
from pathlib import Path

from app.ai.speaker.provider import (
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRoleAssignment,
)
from app.ai.speaker.pyannote_provider import PyannoteDiarizationError
from app.composition.providers import UnsupportedProviderError
from app.composition.services import build_audio_processing_pipeline
from app.composition.speaker_sessions import (
    build_session_role_provider,
    build_speaker_session_registry,
)
from app.core.config import get_settings
from app.domain.utterance import Utterance,SpeakerRole
from app.services.audio_ingestion_service import (
    AudioIngestionError,
    AudioIngestionService,
)
from app.services.audio_processing_pipeline import AudioPipelineError
from app.ai.asr.sarvam_provider import SarvamASRError
from dataclasses import replace

DEFAULT_CHUNKS = tuple(Path(f"../sample_chunk_{i:02d}.wav") for i in range(3))
CALL_ID = "dev-sample-call"
SAMPLE_SPEAKER_ROLES = {
    "SPEAKER_00": SpeakerRole.ICR,
    "SPEAKER_01": SpeakerRole.CUSTOMER,
}

class _RecordingRoleProvider(RoleIdentificationProvider):
    def __init__(self, inner: RoleIdentificationProvider) -> None:
        self._inner = inner
        self.segments: list[DiarizedSegment] = []
        self.assignments: list[SpeakerRoleAssignment] = []

    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        assignments = self._inner.identify_roles(segments)
        self.segments = list(segments)
        self.assignments = list(assignments)
        return assignments


class _UnusedWorkflow:
    def process_utterance(self, call_id: str, utterance: Utterance):
        raise RuntimeError("The workflow service is not used by this runner.")


def _speaker_for(utterance: Utterance, segments: Sequence[DiarizedSegment]) -> str:
    overlaps: dict[str, float] = {}
    for segment in segments:
        overlap = min(segment.end_time, utterance.end_time) - max(
            segment.start_time, utterance.start_time
        )
        if overlap > 0:
            overlaps[segment.speaker_id] = (
                overlaps.get(segment.speaker_id, 0.0) + overlap
            )
    return max(overlaps, key=overlaps.__getitem__) if overlaps else "n/a"

def _shift(
    segments: Sequence[DiarizedSegment], offset: float
) -> list[DiarizedSegment]:
    return [
        replace(
            segment,
            start_time=segment.start_time + offset,
            end_time=segment.end_time + offset,
        )
        for segment in segments
    ]

def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv[1:]] or list(DEFAULT_CHUNKS)
    settings = get_settings().model_copy(update={"diarization_provider": "pyannote"})

    ingestion = AudioIngestionService()
    rows: list[tuple[int, Utterance, str]] = []
    chunk_lines: list[str] = []
    speakers: set[str] = set()
    roles: dict[str, str] = {}
    offset = 0.0

    try:
        session = build_speaker_session_registry().get_or_create(CALL_ID)
        session.assign_many(SAMPLE_SPEAKER_ROLES)
        role_provider = _RecordingRoleProvider(build_session_role_provider(session))
        pipeline = build_audio_processing_pipeline(
            _UnusedWorkflow(),
            (),
            settings=settings,
            role_provider=role_provider,
        )

        for index, path in enumerate(paths):
            ingested = ingestion.load_wav(path)
            metadata = ingested.metadata
            utterances = pipeline.build_utterances(
                ingested.audio, start_offset=offset
            )
            segments = _shift(role_provider.segments, offset)
            rows.extend(
                (index, utterance, _speaker_for(utterance, segments))
                for utterance in utterances
            )
            speakers.update(segment.speaker_id for segment in segments)
            roles.update(
                {a.speaker_id: a.role.value for a in role_provider.assignments}
            )
            chunk_lines.append(
                f"Chunk {index}: {path} | start {offset:.2f}s | "
                f"{metadata.duration_seconds:.2f}s | "
                f"{metadata.sample_rate} Hz | {metadata.channels} ch"
            )
            offset += metadata.duration_seconds
    except (
        AudioIngestionError,
        AudioPipelineError,
        PyannoteDiarizationError,
        SarvamASRError,
        UnsupportedProviderError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if exc.__cause__ is not None:
            print(f"Cause: {exc.__cause__!r}", file=sys.stderr)
        return 1

    rows.sort(key=lambda row: row[1].start_time)

    print(f"Call: {CALL_ID} | chunks: {len(paths)} | total {offset:.2f}s")
    print("\n".join(chunk_lines) + "\n")

    for number, (chunk_index, utterance, speaker_id) in enumerate(rows, start=1):
        print(
            f"[{number}] {utterance.start_time:7.2f} -> {utterance.end_time:7.2f} | "
            f"chunk={chunk_index} | speaker={speaker_id} | "
            f"role={utterance.speaker_role.value} | "
            f"language={','.join(utterance.languages)}"
        )
        print(f"     {utterance.transcript}")

    print(f"\nUtterances: {len(rows)}")
    print(f"Detected speakers: {len(speakers)} ({', '.join(sorted(speakers))})")
    for speaker_id, role in sorted(roles.items()):
        print(f"  {speaker_id} -> {role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))