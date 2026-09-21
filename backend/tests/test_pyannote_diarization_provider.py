from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.speaker.provider import DiarizationProvider
from app.ai.speaker.pyannote_provider import (
    PyannoteDiarizationError,
    PyannoteDiarizationProvider,
)

MODEL = "test/model"


class FakeAnnotation:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label: bool = False):
        for (start, end), speaker in self._tracks:
            yield SimpleNamespace(start=start, end=end), "track", speaker


class FakePipeline:
    def __init__(self, tracks, wrap: bool = True):
        annotation = FakeAnnotation(tracks)
        self._output = (
            SimpleNamespace(speaker_diarization=annotation) if wrap else annotation
        )
        self.paths: list[Path] = []
        self.received: list[bytes] = []

    def __call__(self, path: str):
        self.paths.append(Path(path))
        self.received.append(Path(path).read_bytes())
        return self._output


class ExplodingPipeline:
    def __call__(self, path: str):
        raise RuntimeError("secret internal detail")


def make_provider(pipeline) -> PyannoteDiarizationProvider:
    return PyannoteDiarizationProvider(MODEL, pipeline=pipeline)


def test_is_diarization_provider() -> None:
    assert isinstance(make_provider(FakePipeline([])), DiarizationProvider)


def test_maps_speaker_ids_and_times() -> None:
    pipeline = FakePipeline([((0.0, 1.5), "SPEAKER_00"), ((1.5, 3.0), "SPEAKER_01")])
    result = make_provider(pipeline).diarize(b"audio")
    assert [(s.speaker_id, s.start_time, s.end_time) for s in result] == [
        ("SPEAKER_00", 0.0, 1.5),
        ("SPEAKER_01", 1.5, 3.0),
    ]
    assert all(s.confidence is None for s in result)


def test_segments_are_sorted_by_start_time() -> None:
    pipeline = FakePipeline([((2.0, 3.0), "B"), ((0.0, 2.0), "A")])
    result = make_provider(pipeline).diarize(b"audio")
    assert [s.speaker_id for s in result] == ["A", "B"]


def test_accepts_pipeline_returning_annotation_directly() -> None:
    pipeline = FakePipeline([((0.0, 1.0), "A")], wrap=False)
    result = make_provider(pipeline).diarize(b"audio")
    assert [s.speaker_id for s in result] == ["A"]


def test_empty_diarization_returns_empty_list() -> None:
    assert make_provider(FakePipeline([])).diarize(b"audio") == []


def test_audio_bytes_reach_pipeline_and_temp_file_is_removed() -> None:
    pipeline = FakePipeline([((0.0, 1.0), "A")])
    make_provider(pipeline).diarize(b"wav-bytes")
    assert pipeline.received == [b"wav-bytes"]
    assert not pipeline.paths[0].exists()


def test_empty_audio_is_rejected_without_calling_pipeline() -> None:
    pipeline = FakePipeline([])
    with pytest.raises(ValueError, match="audio"):
        make_provider(pipeline).diarize(b"")
    assert pipeline.paths == []


def test_pipeline_failure_is_wrapped_without_leaking_details() -> None:
    with pytest.raises(PyannoteDiarizationError) as exc_info:
        make_provider(ExplodingPipeline()).diarize(b"audio")
    assert "secret" not in str(exc_info.value)


def test_malformed_pipeline_output_is_wrapped() -> None:
    class BadPipeline:
        def __call__(self, path: str):
            return object()

    with pytest.raises(PyannoteDiarizationError):
        make_provider(BadPipeline()).diarize(b"audio")


def test_pipeline_is_loaded_lazily_and_once() -> None:
    calls: list[tuple[str, str | None]] = []
    pipeline = FakePipeline([((0.0, 1.0), "A")])

    def loader(model: str, token: str | None):
        calls.append((model, token))
        return pipeline

    provider = PyannoteDiarizationProvider(MODEL, "tok", pipeline_loader=loader)
    assert calls == []
    provider.diarize(b"a")
    provider.diarize(b"b")
    assert calls == [(MODEL, "tok")]


def test_injected_pipeline_skips_loader() -> None:
    def loader(model: str, token: str | None):
        raise AssertionError("loader must not be called")

    provider = PyannoteDiarizationProvider(
        MODEL, pipeline=FakePipeline([((0.0, 1.0), "A")]), pipeline_loader=loader
    )
    assert len(provider.diarize(b"audio")) == 1


def test_loader_failure_is_wrapped() -> None:
    def loader(model: str, token: str | None):
        raise ImportError("pyannote missing")

    provider = PyannoteDiarizationProvider(MODEL, pipeline_loader=loader)
    with pytest.raises(PyannoteDiarizationError):
        provider.diarize(b"audio")


def test_rejects_empty_model() -> None:
    with pytest.raises(ValueError, match="model"):
        PyannoteDiarizationProvider("  ")