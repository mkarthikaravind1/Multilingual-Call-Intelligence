import logging
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ai.speaker.provider import DiarizationProvider, DiarizationError, DiarizedSegment

logger = logging.getLogger(__name__)


class PyannoteDiarizationError(DiarizationError):
    pass


_pipelines: dict[tuple[str, str | None], Any] = {}
# Held for the whole load, so a call arriving during the startup warm-up waits
# for that load instead of starting a second one alongside it.
_pipelines_lock = threading.Lock()


def _load_pipeline(model: str, token: str | None) -> Any:
    key = (model, token)
    with _pipelines_lock:
        if key not in _pipelines:
            logger.info("Loading diarization model %s", model)
            started = time.monotonic()
            _pipelines[key] = _load_pipeline_uncached(model, token)
            logger.info(
                "Diarization model ready (%.1fs)", time.monotonic() - started
            )
        return _pipelines[key]


def _load_pipeline_uncached(model: str, token: str | None) -> Any:
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    from pyannote.audio import Pipeline

    # Load from the local cache when the model is already downloaded, which
    # skips a round of Hugging Face network checks for every model file.
    checkpoint: str = model
    if not Path(model).exists():
        try:
            checkpoint = snapshot_download(model, token=token, local_files_only=True)
        except LocalEntryNotFoundError:
            logger.info("Diarization model is not cached; downloading %s", model)

    pipeline = Pipeline.from_pretrained(checkpoint, token=token)
    if pipeline is None:
        raise RuntimeError("Pipeline.from_pretrained returned None.")
    return pipeline


def _set_torch_threads(threads: int) -> None:
    import torch

    # Process-wide: pyannote is the only torch user in this service.
    torch.set_num_threads(threads)


class PyannoteDiarizationProvider(DiarizationProvider):
    def __init__(
        self,
        model: str,
        token: str | None = None,
        *,
        pipeline: Callable[[str], Any] | None = None,
        pipeline_loader: Callable[[str, str | None], Any] | None = None,
        cpu_threads: int = 0,
        set_cpu_threads: Callable[[int], None] | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty.")
        self._model = model
        self._token = token
        self._pipeline = pipeline
        self._pipeline_loader = pipeline_loader or _load_pipeline
        self._cpu_threads = cpu_threads
        self._set_cpu_threads = set_cpu_threads or _set_torch_threads

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

    def warm_up(self) -> None:
        self._get_pipeline()

    def _get_pipeline(self) -> Callable[[str], Any]:
        if self._pipeline is None:
            if self._cpu_threads > 0:
                self._set_cpu_threads(self._cpu_threads)
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