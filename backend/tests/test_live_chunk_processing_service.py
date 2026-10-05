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
        # (continues_previous, ends_utterance) per processed chunk.
        self.continuity: list[tuple[bool, bool]] = []

    def process_audio(
        self,
        call_id: str,
        audio: bytes,
        start_offset: float = 0.0,
        *,
        continues_previous: bool = False,
        ends_utterance: bool = True,
        track: str | None = None,
        speaker_role=None,
    ) -> CallAnalysisResult:
        if self.error is not None:
            raise self.error
        self.calls.append((call_id, audio, start_offset))
        self.continuity.append((continues_previous, ends_utterance))
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


class ScriptedProcessor(FakeProcessor):
    """Fails the chunks whose (0-based) call index is in `fail_on`."""

    def __init__(self, fail_on: set[int]) -> None:
        super().__init__()
        self._fail_on = fail_on
        self.attempts = 0

    def process_audio(
        self, call_id: str, audio: bytes, start_offset: float = 0.0, **continuity
    ) -> CallAnalysisResult:
        attempt = self.attempts
        self.attempts += 1
        if attempt in self._fail_on:
            raise AudioPipelineError(f"chunk attempt {attempt} failed")
        return super().process_audio(call_id, audio, start_offset, **continuity)


def _scripted_service(*fail_on: int) -> tuple[LiveChunkProcessingService, ScriptedProcessor]:
    processor = ScriptedProcessor(set(fail_on))
    return LiveChunkProcessingService(lambda call_id: processor), processor


def test_pipeline_error_propagates_and_consumes_the_chunk():
    service, processor = _scripted_service(1)
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    with pytest.raises(AudioPipelineError, match="failed"):
        service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))

    # The failed chunk is consumed: the stream moves on to the next sequence.
    service.process_chunk("call-1", make_chunk(2, 2.0, 3.0))
    assert [offset for _, _, offset in processor.calls] == [0.0, 2.0]


def test_first_chunk_failure_does_not_block_following_chunks():
    service, processor = _scripted_service(0)

    with pytest.raises(AudioPipelineError):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))
    service.process_chunk("call-1", make_chunk(2, 2.0, 3.0))

    assert [offset for _, _, offset in processor.calls] == [1.0, 2.0]


def test_multiple_failures_followed_by_a_successful_chunk():
    service, processor = _scripted_service(0, 1, 2)

    for sequence in range(3):
        with pytest.raises(AudioPipelineError):
            service.process_chunk(
                "call-1", make_chunk(sequence, float(sequence), sequence + 1.0)
            )
    result = service.process_chunk("call-1", make_chunk(3, 3.0, 4.0))

    assert result.sequence == 3
    assert [offset for _, _, offset in processor.calls] == [3.0]


def test_failed_chunk_replay_is_still_rejected_as_duplicate():
    service, processor = _scripted_service(0)
    with pytest.raises(AudioPipelineError):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    with pytest.raises(DuplicateChunkError):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    assert processor.attempts == 1


def test_out_of_order_chunk_after_failure_is_still_rejected():
    service, processor = _scripted_service(0)
    with pytest.raises(AudioPipelineError):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    with pytest.raises(OutOfOrderChunkError, match="expected sequence 1"):
        service.process_chunk("call-1", make_chunk(2, 2.0, 3.0))
    assert processor.attempts == 1


def test_order_errors_do_not_consume_the_expected_sequence(service, factory):
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    with pytest.raises(OutOfOrderChunkError):
        service.process_chunk("call-1", make_chunk(3, 3.0, 4.0))

    service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))
    assert len(factory.processors["call-1"].calls) == 2


def test_failed_final_chunk_still_terminates_the_stream():
    service, _ = _scripted_service(1)
    service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    with pytest.raises(AudioPipelineError):
        service.process_chunk("call-1", make_chunk(1, 1.0, 2.0, final=True))

    assert service.is_completed("call-1") is True
    with pytest.raises(StreamCompletedError):
        service.process_chunk("call-1", make_chunk(2, 2.0, 3.0))


def test_stream_terminates_normally_after_an_earlier_failed_chunk():
    service, processor = _scripted_service(0)
    with pytest.raises(AudioPipelineError):
        service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))

    result = service.process_chunk("call-1", make_chunk(1, 1.0, 2.0, final=True))

    assert result.is_final is True
    assert service.is_completed("call-1") is True
    assert len(processor.calls) == 1


def test_pipeline_build_failure_consumes_the_chunk_and_is_retried_next_chunk():
    built: list[str] = []

    def flaky_factory(call_id: str) -> FakeProcessor:
        built.append(call_id)
        if len(built) == 1:
            raise RuntimeError("factory failed")
        return FakeProcessor()

    flaky_service = LiveChunkProcessingService(flaky_factory)

    with pytest.raises(RuntimeError, match="factory failed"):
        flaky_service.process_chunk("call-1", make_chunk(0, 0.0, 1.0))
    assert flaky_service.is_completed("call-1") is False

    flaky_service.process_chunk("call-1", make_chunk(1, 1.0, 2.0))
    flaky_service.process_chunk("call-1", make_chunk(2, 2.0, 3.0))
    assert built == ["call-1", "call-1"]


@pytest.mark.parametrize("call_id", ["", "   "])
def test_empty_call_id_is_rejected(service, call_id):
    with pytest.raises(LiveChunkProcessingError, match="call_id"):
        service.process_chunk(call_id, make_chunk())


def test_non_chunk_input_is_rejected(service):
    with pytest.raises(LiveChunkProcessingError, match="AudioChunk"):
        service.process_chunk("call-1", b"audio")  # type: ignore[arg-type]

def test_chunk_continuity_reaches_the_processor(service, factory):
    service.process_chunk(
        "call-1",
        AudioChunk(sequence=0, start_time=0.0, end_time=3.0, audio=b"a"),
    )
    service.process_chunk(
        "call-1",
        AudioChunk(
            sequence=1, start_time=3.0, end_time=5.0, audio=b"b",
            continues_previous=True, ends_on_pause=True,
        ),
    )
    service.process_chunk(
        "call-1",
        AudioChunk(
            sequence=2, start_time=5.0, end_time=6.0, audio=b"c",
            continues_previous=True, is_final=True,
        ),
    )

    # A time-limit cut keeps the utterance open; a pause or the end of the
    # stream closes it.
    assert factory.processors["call-1"].continuity == [
        (False, False),
        (True, True),
        (True, True),
    ]
