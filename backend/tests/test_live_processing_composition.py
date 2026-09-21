import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.speaker.provider import DiarizedSegment
from app.composition.live_processing import build_live_chunk_processing_service
from app.composition.services import (
    build_call_service,
    build_call_workflow_service,
)
from app.composition.speaker_sessions import build_speaker_session_registry
from app.core.config import Settings
from app.domain.utterance import SpeakerRole
from app.services.audio_chunking_service import AudioChunk
from app.services.call_workflow_service import CallAnalysisResult
from app.services.live_chunk_processing_service import (
    OutOfOrderChunkError,
    StreamCompletedError,
)


class FakeLLMClient(LLMClient):
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="[]")


class FakeASRProvider(ASRProvider):
    def transcribe(self, audio: bytes) -> ASRResult:
        return ASRResult(
            transcript="The bill is too high",
            detected_language="en",
            start_time=0.0,
            end_time=2.0,
        )


class FakeLanguageProvider(LanguageIdentificationProvider):
    def identify(self, text: str) -> LanguageIdentificationResult:
        return LanguageIdentificationResult(languages=[LanguageSpan(language="en")])


def make_settings() -> Settings:
    return Settings(
        _env_file=None, # type: ignore
        diarization_provider="scripted",
        role_provider="order_based",
    )  # type: ignore


def make_chunk(sequence: int, final: bool = False) -> AudioChunk:
    return AudioChunk(
        sequence=sequence,
        start_time=sequence * 2.0,
        end_time=sequence * 2.0 + 2.0,
        audio=b"audio",
        is_final=final,
    )


def build_live(*call_ids: str):
    call_service = build_call_service()
    workflow = build_call_workflow_service(
        llm_client=FakeLLMClient(), call_service=call_service
    )
    registry = build_speaker_session_registry()
    service = build_live_chunk_processing_service(
        workflow,
        [DiarizedSegment("s0", 0.0, 2.0)],
        settings=make_settings(),
        asr_provider=FakeASRProvider(),
        language_provider=FakeLanguageProvider(),
        registry=registry,
    )
    for call_id in call_ids:
        call_service.start_call(call_id)
    return call_service, service, registry


def test_chunks_flow_through_real_pipeline_with_offsets_and_stable_role():
    call_service, service, registry = build_live("call-1")

    for sequence in range(3):
        result = service.process_chunk("call-1", make_chunk(sequence))
        assert isinstance(result.analysis, CallAnalysisResult)

    utterances = call_service.get_call("call-1").utterances
    assert [u.start_time for u in utterances] == [0.0, 2.0, 4.0]
    assert [u.end_time for u in utterances] == [2.0, 4.0, 6.0]
    assert [u.speaker_role for u in utterances] == [SpeakerRole.ICR] * 3
    session = registry.get("call-1")
    assert session is not None
    assert session.role_for("s0") == SpeakerRole.ICR


def test_calls_use_independent_speaker_sessions():
    call_service, service, registry = build_live("call-1", "call-2")

    service.process_chunk("call-1", make_chunk(0))
    service.process_chunk("call-2", make_chunk(0))
    service.process_chunk("call-1", make_chunk(1))

    assert registry.get("call-1") is not registry.get("call-2")
    assert call_service.get_call("call-1").utterance_count == 2
    assert call_service.get_call("call-2").utterance_count == 1


def test_final_chunk_completes_stream_with_real_pipeline():
    _, service, _ = build_live("call-1")

    service.process_chunk("call-1", make_chunk(0))
    service.process_chunk("call-1", make_chunk(1, final=True))

    assert service.is_completed("call-1") is True
    with pytest.raises(StreamCompletedError):
        service.process_chunk("call-1", make_chunk(2))


def test_out_of_order_chunk_adds_no_utterance():
    call_service, service, _ = build_live("call-1")

    with pytest.raises(OutOfOrderChunkError):
        service.process_chunk("call-1", make_chunk(1))

    assert call_service.get_call("call-1").utterance_count == 0