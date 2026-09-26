import tempfile
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.speaker.provider import DiarizationProvider, DiarizationError, DiarizedSegment


class PyannoteDiarizationError(DiarizationError):
    pass


@lru_cache(maxsize=4)
def _load_pipeline(model: str, token: str | None) -> Any:
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(model, token=token)
    if pipeline is None:
        raise RuntimeError("Pipeline.from_pretrained returned None.")
    return pipeline


class PyannoteDiarizationProvider(DiarizationProvider):
    def __init__(
        self,
        model: str,
        token: str | None = None,
        *,
        pipeline: Callable[[str], Any] | None = None,
        pipeline_loader: Callable[[str, str | None], Any] | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty.")
        self._model = model
        self._token = token
        self._pipeline = pipeline
        self._pipeline_loader = pipeline_loader or _load_pipeline

    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        if not audio:
            raise ValueError("audio must not be empty.")
        pipeline = self._get_pipeline()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "audio.wav"
                path.write_bytes(audio)
                output = pipeline(str(path))
            return self._to_segments(output)
        except Exception as exc:
            raise PyannoteDiarizationError("Pyannote diarization failed.") from exc

    def _get_pipeline(self) -> Callable[[str], Any]:
        if self._pipeline is None:
            try:
                self._pipeline = self._pipeline_loader(self._model, self._token)
            except Exception as exc:
                raise PyannoteDiarizationError(
                    "Pyannote pipeline could not be loaded."
                ) from exc
        return self._pipeline

    @staticmethod
    def _to_segments(output: Any) -> list[DiarizedSegment]:
        annotation = getattr(output, "speaker_diarization", output)
        segments = [
            DiarizedSegment(
                speaker_id=str(speaker),
                start_time=float(turn.start),
                end_time=float(turn.end),
            )
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        ]
        return sorted(segments, key=lambda segment: segment.start_time)