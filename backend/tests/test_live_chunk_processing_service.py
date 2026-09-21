import pytest
from typing import cast
from app.services.audio_chunking_service import AudioChunk
from app.services.audio_processing_pipeline import AudioPipelineError
from app.services.live_chunk_processing_service import (
    ChunkOrderError,
    ChunkProcessingResult,
    DuplicateChunkError,
    LiveChunkProcessingError,
    LiveChunkProcessingService,
    OutOfOrderChunkError,
    StreamCompletedError,
)
from app.services.call_workflow_service import CallAnalysisResult


class FakeProcessor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, float]] = []
        self.results: list[CallAnalysisResult] = []
        self.error: Exception | None = None

    def process_audio(
        self, call_id: str, audio: bytes, start_offset: float = 0.0
    ) -> CallAnalysisResult:
        if self.error is not None:
            raise self.error
        self.calls.append((call_id, audio, start_offset))
        result = cast(CallAnalysisResult, object())
        self.results.append(result)
        return result


class FakeFactory:
    def __init__(self) -> None:
        self.processors: dict[str, FakeProcessor] = {}
        self.created: list[str] = []

    def __call__(self, call_id: str) -> FakeProcessor:
        self.created.append(call_id)
        processor = FakeProcessor()
        self.processors[call_id] = processor
        return processor


def make_chunk(
    sequence: int = 0,
    start: float = 0.0,
    end: float = 1.0,
    audio: bytes = b"audio",
    final: bool = False,
) -> AudioChunk:
    return AudioChunk(
        sequence=sequence,
        start_time=start,
        end_time=end,
        audio=audio,
        is_final=final,
    )


@pytest.fixture
def factory() -> FakeFactory:
    return FakeFactory()


@pytest.fixture
def service(factory: FakeFactory) -> LiveChunkProcessingService:
    return LiveChunkProcessingService(factory)


def test_chunks_are_processed_sequentially_with_start_offsets(service, factory):
    chunks = [
        make_chunk(0, 0.0, 5.0, b"a"),
        make_chunk(1, 5.0, 10.0, b"b"),
        make_chunk(2, 10.0, 12.5, b"c"),
    ]

    results = [service.process_chunk("call-1", chunk) for chunk in chunks]

    assert factory.processors["call-1"].calls == [
        ("call-1", b"a", 0.0),
        ("call-1", b"b", 5.0),
        ("call-1", b"c", 10.0),
    ]
    assert [r.sequence for r in results] == [0, 1, 2]
    assert [(r.start_time, r.end_time) for r in results] == [
        (0.0, 5.0),
        (5.0, 10.0),
        (10.0, 12.5),
    ]


def test_result_carries_pipeline_analysis_and_chunk_details(service, factory):
    result = service.process_chunk("call-1", make_chunk(0, 0.0, 2.0))

    assert isinstance(result, ChunkProcessingResult)
    assert result.call_id == "call-1"
    assert result.analysis is factory.processors["call-1"].results[0]
    assert result.is_final is False


def test_pipeline_is_created_once_per_call(service, factory):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))

    assert factory.created == ["call-1"]


def test_duplicate_chunk_is_rejected_without_reprocessing(service, factory):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    with pytest.raises(DuplicateChunkError, match="already processed"):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    assert len(factory.processors["call-1"].calls) == 1


def test_replayed_older_chunk_is_rejected_as_duplicate(service):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))

    with pytest.raises(DuplicateChunkError):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))


def test_skipped_sequence_is_rejected_and_state_is_unchanged(service, factory):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    with pytest.raises(OutOfOrderChunkError, match="expected sequence 1"):
        service.process_chunk("call-1", make_chunk(2, 2.0, 3.0))

    service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))
    assert len(factory.processors["call-1"].calls) == 2


def test_first_chunk_must_have_sequence_zero(service, factory):
    with pytest.raises(OutOfOrderChunkError, match="expected sequence 0"):
        service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))

    assert factory.created == []


def test_chunk_starting_before_previous_end_is_rejected(service):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    with pytest.raises(OutOfOrderChunkError, match="before the previous chunk ends"):
        service.process_chunk("call-1", make_chunk(1, 0.5, 1.5))


def test_order_errors_share_a_common_base():
    assert issubclass(DuplicateChunkError, ChunkOrderError)
    assert issubclass(OutOfOrderChunkError, ChunkOrderError)
    assert issubclass(ChunkOrderError, LiveChunkProcessingError)


def test_final_chunk_completes_the_stream(service):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    assert service.is_completed("call-1") is False

    result = service.process_chunk("call-1", make_chunk(1, 1.0, 1.5, final=True))

    assert result.is_final is True
    assert service.is_completed("call-1") is True


def test_chunks_after_final_are_rejected(service, factory):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0, final=True))

    with pytest.raises(StreamCompletedError, match="already complete"):
        service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))
    with pytest.raises(StreamCompletedError):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0, final=True))

    assert len(factory.processors["call-1"].calls) == 1


def test_single_final_chunk_stream_is_valid(service):
    service.process_chunk("call-1", make_chunk(0, 0.0, 0.5, final=True))

    assert service.is_completed("call-1") is True


def test_unknown_call_is_not_completed(service):
    assert service.is_completed("missing") is False


def test_multiple_calls_are_tracked_independently(service, factory):
    service.process_chunk("call-a", make_chunk(0, 0.0, 1.0))
    service.process_chunk("call-b", make_chunk(0, 0.0, 1.0))
    service.process_chunk("call-a", make_chunk(1, 1.0, 2.0, final=True))
    service.process_chunk("call-b", make_chunk(1, 1.0, 2.0))

    assert service.is_completed("call-a") is True
    assert service.is_completed("call-b") is False
    assert factory.processors["call-a"] is not factory.processors["call-b"]
    assert len(factory.processors["call-a"].calls) == 2
    assert len(factory.processors["call-b"].calls) == 2
    with pytest.raises(StreamCompletedError):
        service.process_chunk("call-a", make_chunk(2, 2.0, 3.0))
    service.process_chunk("call-b", make_chunk(2, 2.0, 3.0))


def test_pipeline_error_propagates_and_chunk_can_be_retried(service, factory):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    factory.processors["call-1"].error = AudioPipelineError("boom")

    with pytest.raises(AudioPipelineError, match="boom"):
        service.process_chunk("call-1", make_chunk(1, 1.0, 2.0, final=True))

    assert service.is_completed("call-1") is False
    factory.processors["call-1"].error = None
    service.process_chunk("call-1", make_chunk(1, 1.0, 2.0, final=True))
    assert service.is_completed("call-1") is True


def test_first_chunk_error_does_not_create_stream_state(service, factory):
    def failing_factory(call_id: str) -> FakeProcessor:
        raise RuntimeError("factory failed")

    failing_service = LiveChunkProcessingService(failing_factory)

    with pytest.raises(RuntimeError, match="factory failed"):
        failing_service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    assert failing_service.is_completed("call-1") is False


@pytest.mark.parametrize("call_id", ["", "   "])
def test_empty_call_id_is_rejected(service, call_id):
    with pytest.raises(LiveChunkProcessingError, match="call_id"):
        service.process_chunk(call_id, make_chunk())


def test_non_chunk_input_is_rejected(service):
    with pytest.raises(LiveChunkProcessingError, match="AudioChunk"):
        service.process_chunk("call-1", b"audio")  # type: ignore[arg-type]