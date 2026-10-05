import io
import logging
import tempfile
import threading
import time
import wave
import warnings
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.speaker.provider import DiarizationProvider, DiarizationError, DiarizedSegment

logger = logging.getLogger(__name__)

# pyannote warns on chunks that end in silence (a speaker with no frames to
# pool): harmless, and it would otherwise print on most live chunks.
warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)
warnings.filterwarnings("ignore", message="invalid value encountered in divide", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=r"std\(\): degrees of freedom", category=UserWarning)


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
            segments = self._to_segments(output)
        except Exception as exc:
            raise PyannoteDiarizationError("Pyannote diarization failed.") from exc
        return _with_voice_embeddings(segments, output, audio, pipeline)

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


# Voice embeddings: computed from each speaker's own speech (overlaps left
# out) with the pipeline's speaker-embedding model. The pipeline's own
# per-speaker embeddings are not used: on a few seconds of 8 kHz phone audio
# they barely tell speakers apart (cosine ~0.9 between different people),
# while these do (~0.6 same speaker, ~0.2 different, measured on a two-speaker
# call cut into 3 s chunks).
_EMBEDDING_SAMPLE_RATE = 16000
_MIN_EMBEDDING_SECONDS = 0.4


def _with_voice_embeddings(
    segments: list[DiarizedSegment], output: Any, audio: bytes, pipeline: Any
) -> list[DiarizedSegment]:
    model = getattr(pipeline, "_embedding", None)
    annotation = getattr(output, "speaker_diarization", output)
    if model is None or not segments or not hasattr(annotation, "get_overlap"):
        return segments
    try:
        samples, sample_rate = _read_wav(audio)
        overlap = annotation.get_overlap()
        embeddings: dict[str, tuple[float, ...]] = {}
        for label in annotation.labels():
            timeline = annotation.label_timeline(label).extrude(overlap)
            parts = [
                samples[int(seg.start * sample_rate) : int(seg.end * sample_rate)]
                for seg in timeline
            ]
            speech = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
            if len(speech) < _MIN_EMBEDDING_SECONDS * sample_rate:
                continue  # too little speech for a reliable voice print
            vector = _embed(model, _resample(speech, sample_rate))
            if vector is not None:
                embeddings[str(label)] = vector
    except Exception:
        logger.warning("Could not compute the speakers' voice embeddings.", exc_info=True)
        return segments
    return [
        replace(segment, embedding=embeddings.get(segment.speaker_id)) for segment in segments
    ]


def _read_wav(audio: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(audio)) as source:
        if source.getsampwidth() != 2:
            raise ValueError("Only 16-bit audio is supported for voice embeddings.")
        channels = source.getnchannels()
        rate = source.getframerate()
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm.astype(np.float32) / 32768.0, rate


def _resample(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == _EMBEDDING_SAMPLE_RATE:
        return samples
    duration = len(samples) / sample_rate
    target = np.arange(int(duration * _EMBEDDING_SAMPLE_RATE)) / _EMBEDDING_SAMPLE_RATE
    source = np.arange(len(samples)) / sample_rate
    return np.interp(target, source, samples).astype(np.float32)


def _embed(model: Any, samples: np.ndarray) -> tuple[float, ...] | None:
    import torch

    with torch.inference_mode():
        result = model(torch.from_numpy(samples)[None, None])
    vector = np.asarray(result, dtype=float).reshape(-1)
    if not len(vector) or not np.all(np.isfinite(vector)):
        return None
    return tuple(float(value) for value in vector)
