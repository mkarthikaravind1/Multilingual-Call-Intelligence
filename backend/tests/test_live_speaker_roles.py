"""Live speaker roles: separate call tracks, voice tracking across chunks,
content evidence, the optional LLM judge, and the Plivo stream that carries
both sides of a call."""

import base64
import json
import math

import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.speaker.content_role_scorer import ContentRoleScorer
from app.ai.speaker.llm_role_judge import LLMRoleJudge
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    SpeakerRole as AISpeakerRole,
)
from app.ai.speaker.session_role_provider import (
    SessionRoleIdentificationProvider,
    SpeakerEvidenceStore,
)
from app.ai.speaker.voice_tracker import VoiceTracker
from app.core.config import Settings
from app.domain.conversation import UtteranceNotLatestError
from app.domain.speaker_session import SpeakerSession
from app.domain.utterance import SpeakerRole, Utterance
from app.services.audio_chunking_service import AudioChunk
from app.services.audio_processing_pipeline import AudioProcessingPipeline
from app.services.live_chunk_processing_service import (
    DuplicateChunkError,
    LiveChunkProcessingService,
)
from app.services.live_state_store import InMemoryLiveStateStore
from app.services.speaker_session_registry import SpeakerSessionRegistry
from app.telephony.plivo.provider import (
    PlivoTelephonyProvider,
    parse_plivo_media_stream_event,
)

try:
    import audioop
except ImportError:  # pragma: no cover
    audioop = None

ICR_VOICE = (1.0, 0.0, 0.0)
CUSTOMER_VOICE = (0.0, 1.0, 0.0)


def _near(voice: tuple[float, ...], wobble: float = 0.1) -> tuple[float, ...]:
    return (voice[0] + wobble, voice[1] + wobble, voice[2] + wobble)


def seg(label: str, voice=None, start=0.0, end=2.0) -> DiarizedSegment:
    return DiarizedSegment(label, start, end, embedding=voice)


# ---- VoiceTracker ----

def test_tracker_keeps_one_id_per_voice_whatever_the_chunk_labels():
    tracker = VoiceTracker()

    first = tracker.match([seg("SPEAKER_00", ICR_VOICE), seg("SPEAKER_01", CUSTOMER_VOICE)])
    # The diarizer swaps its labels in the next chunk.
    second = tracker.match(
        [seg("SPEAKER_00", _near(CUSTOMER_VOICE)), seg("SPEAKER_01", _near(ICR_VOICE))]
    )

    assert first == {"SPEAKER_00": "speaker_1", "SPEAKER_01": "speaker_2"}
    assert second == {"SPEAKER_00": "speaker_2", "SPEAKER_01": "speaker_1"}


def test_tracker_never_creates_more_speakers_than_the_call_has():
    tracker = VoiceTracker(max_speakers=2)
    tracker.match([seg("A", ICR_VOICE)])
    tracker.match([seg("B", CUSTOMER_VOICE)])

    # Somewhat like the customer: given to the nearest known speaker.
    third = tracker.match([seg("C", (0.3, 1.0, 0.3))])

    assert third == {"C": "speaker_2"}
    assert tracker.speaker_ids == ("speaker_1", "speaker_2")


def test_a_short_fragment_never_becomes_a_new_speaker():
    """The live failure: "today?" cut off the ICR's greeting (0.8 s) came
    out unlike her voice, became a second speaker, and the customer was then
    forced onto the ICR."""
    tracker = VoiceTracker()
    tracker.match([seg("SPEAKER_00", ICR_VOICE, 0.0, 3.0)])

    fragment = tracker.match([seg("SPEAKER_00", (0.0, 0.0, 1.0), 0.0, 0.8)])
    customer = tracker.match([seg("SPEAKER_00", CUSTOMER_VOICE, 0.0, 3.0)])

    assert fragment == {}
    assert customer == {"SPEAKER_00": "speaker_2"}


def test_a_voice_unlike_every_known_speaker_is_not_forced_onto_one():
    tracker = VoiceTracker()
    tracker.match([seg("A", ICR_VOICE), seg("B", CUSTOMER_VOICE)])

    assert tracker.match([seg("C", (-1.0, -1.0, 0.0), 0.0, 3.0)]) == {}


def test_a_short_fragment_still_joins_a_speaker_it_clearly_matches():
    tracker = VoiceTracker()
    tracker.match([seg("A", ICR_VOICE, 0.0, 3.0)])

    assert tracker.match([seg("X", _near(ICR_VOICE), 0.0, 0.6)]) == {"X": "speaker_1"}


def test_tracker_leaves_out_labels_without_a_voice_embedding():
    assert VoiceTracker().match([seg("A", None)]) == {}


def test_tracker_state_round_trips():
    tracker = VoiceTracker()
    tracker.match([seg("A", ICR_VOICE), seg("B", CUSTOMER_VOICE)])

    restored = VoiceTracker()
    restored.load(json.loads(json.dumps(tracker.to_dict())))

    assert restored.match([seg("X", _near(CUSTOMER_VOICE))]) == {"X": "speaker_2"}


# ---- ContentRoleScorer ----

@pytest.mark.parametrize(
    "text",
    [
        "Good morning, thank you for calling ABC Motors, how may I help you?",
        "வணக்கம் சார், உங்களுக்கு எப்படி உதவ முடியும்?",
        "నమస్కారం, మీకు ఎలా సహాయం చేయగలను?",
    ],
)
def test_icr_greetings_score_as_icr(text):
    assert ContentRoleScorer().score(text) >= 3


@pytest.mark.parametrize(
    "text",
    [
        "I am calling about my car, it is still not ready",
        "என் வண்டி இன்னும் ரெடி ஆகலை",
        "എന്റെ വണ്ടി ഇതുവരെ കിട്ടിയില്ല",
    ],
)
def test_customer_speech_scores_as_customer(text):
    assert ContentRoleScorer().score(text) <= -2


def test_configured_icr_phrases_count_as_strong_evidence():
    scorer = ContentRoleScorer(["Welcome to Sri Murugan Motors"])

    assert scorer.score("hello, welcome to sri murugan motors") >= 3


def test_neutral_speech_scores_zero():
    assert ContentRoleScorer().score("okay okay") == 0


# ---- SessionRoleIdentificationProvider ----

class _FakeLLM(LLMClient):
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        return LLMResponse(self.text)


def _provider(session=None, store=None, llm=None):
    session = session or SpeakerSession("call-1")
    provider = SessionRoleIdentificationProvider(
        session,
        evidence_store=store,
        llm_judge=LLMRoleJudge(llm) if llm is not None else None,
    )
    return provider, session


def _roles(provider, segments):
    return {a.speaker_id: a.role for a in provider.identify_roles(segments)}


def test_track_roles_are_recorded_in_the_session():
    provider, session = _provider()

    learned = provider.observe_speech("inbound", "hello", role=AISpeakerRole.CUSTOMER)

    assert learned == AISpeakerRole.CUSTOMER
    assert session.role_for("inbound") == SpeakerRole.CUSTOMER


def test_roles_stay_unknown_until_speech_gives_evidence():
    provider, session = _provider()

    roles = _roles(provider, [seg("SPEAKER_00", ICR_VOICE), seg("SPEAKER_01", CUSTOMER_VOICE, 2, 4)])
    learned = provider.observe_speech("SPEAKER_00", "hello")

    assert roles == {"SPEAKER_00": AISpeakerRole.UNKNOWN, "SPEAKER_01": AISpeakerRole.UNKNOWN}
    assert learned is None
    assert dict(session.roles) == {}


def test_icr_greeting_decides_both_roles_and_they_follow_the_voices():
    provider, session = _provider()
    _roles(provider, [seg("SPEAKER_00", ICR_VOICE), seg("SPEAKER_01", CUSTOMER_VOICE, 2, 4)])

    learned = provider.observe_speech("SPEAKER_00", "Thank you for calling, how can I help you?")
    # Next chunk: the diarizer has swapped its labels.
    later = _roles(provider, [seg("SPEAKER_00", _near(CUSTOMER_VOICE)), seg("SPEAKER_01", _near(ICR_VOICE), 2, 4)])

    assert learned == AISpeakerRole.ICR
    assert session.role_for("speaker_1") == SpeakerRole.ICR
    assert session.role_for("speaker_2") == SpeakerRole.CUSTOMER
    assert later == {"SPEAKER_00": AISpeakerRole.CUSTOMER, "SPEAKER_01": AISpeakerRole.ICR}


def test_customer_evidence_makes_the_other_speaker_the_icr():
    provider, session = _provider()
    _roles(provider, [seg("A", ICR_VOICE), seg("B", CUSTOMER_VOICE, 2, 4)])

    provider.observe_speech("B", "I am calling about my car, it is still not ready")

    assert session.role_for("speaker_1") == SpeakerRole.ICR
    assert session.role_for("speaker_2") == SpeakerRole.CUSTOMER


def test_a_role_once_decided_is_never_changed():
    provider, session = _provider()
    _roles(provider, [seg("A", ICR_VOICE), seg("B", CUSTOMER_VOICE, 2, 4)])
    provider.observe_speech("A", "thank you for calling, how may I help")

    _roles(provider, [seg("B", CUSTOMER_VOICE)])
    provider.observe_speech("B", "thank you for calling, how may I help")

    assert session.role_for("speaker_1") == SpeakerRole.ICR
    assert session.role_for("speaker_2") == SpeakerRole.CUSTOMER


def test_llm_judge_decides_when_phrases_do_not():
    llm = _FakeLLM('{"icr": "speaker_2", "confidence": 0.9}')
    provider, session = _provider(llm=llm)
    for _ in range(2):
        _roles(provider, [seg("A", ICR_VOICE)])
        provider.observe_speech("A", "hmm okay")
        _roles(provider, [seg("B", CUSTOMER_VOICE)])
        provider.observe_speech("B", "yes yes")

    assert len(llm.prompts) == 1
    assert session.role_for("speaker_2") == SpeakerRole.ICR
    assert session.role_for("speaker_1") == SpeakerRole.CUSTOMER


def test_unsure_llm_answer_is_ignored():
    llm = _FakeLLM('{"icr": "speaker_1", "confidence": 0.4}')
    provider, session = _provider(llm=llm)
    for _ in range(2):
        _roles(provider, [seg("A", ICR_VOICE), seg("B", CUSTOMER_VOICE, 2, 4)])
        provider.observe_speech("A", "hmm okay")
        provider.observe_speech("B", "yes yes")

    assert dict(session.roles) == {}


def test_voices_and_evidence_survive_a_new_instance_through_the_shared_store():
    registry = SpeakerSessionRegistry(InMemoryLiveStateStore())
    first, _ = _provider(registry.get_or_create("call-9"), registry.evidence_store("call-9"))
    _roles(first, [seg("A", ICR_VOICE), seg("B", CUSTOMER_VOICE, 2, 4)])
    first.observe_speech("A", "thank you for calling")

    second, _ = _provider(registry.get_or_create("call-9"), registry.evidence_store("call-9"))
    roles = _roles(second, [seg("Z", _near(ICR_VOICE))])

    assert roles == {"Z": AISpeakerRole.ICR}


# ---- AudioProcessingPipeline with tracks ----

class _ASR(ASRProvider):
    def __init__(self, results):
        self._results = list(results)

    def transcribe(self, audio: bytes) -> ASRResult:
        text, start, end = self._results.pop(0)
        return ASRResult(text, "en", start, end, 0.9)


class _Language(LanguageIdentificationProvider):
    def identify(self, text: str) -> LanguageIdentificationResult:
        return LanguageIdentificationResult([LanguageSpan("en", 0.99)])


class _Diarization(DiarizationProvider):
    def __init__(self, chunks=()):
        self.calls = 0
        self._chunks = list(chunks)

    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        self.calls += 1
        return self._chunks.pop(0)


class _Workflow:
    def __init__(self) -> None:
        self.utterances: list[Utterance] = []

    def process_utterance(self, call_id: str, utterance: Utterance):
        self.utterances.append(utterance)

    def process_utterance_update(self, call_id: str, utterance: Utterance):
        if self.utterances[-1].utterance_id != utterance.utterance_id:
            raise UtteranceNotLatestError(utterance.utterance_id)
        self.utterances[-1] = utterance


def _pipeline(asr_results, diarization=None, session=None):
    workflow = _Workflow()
    session = session or SpeakerSession("call-1")
    diarization = diarization or _Diarization()
    pipeline = AudioProcessingPipeline(
        asr_provider=_ASR(asr_results),
        language_provider=_Language(),
        diarization_provider=diarization,
        role_provider=SessionRoleIdentificationProvider(session),
        workflow_service=workflow,
    )
    return pipeline, workflow, diarization, session


def test_track_chunks_take_the_track_role_without_diarization():
    pipeline, workflow, diarization, session = _pipeline(
        [("thank you for calling", 0.1, 1.0), ("my car is not ready", 0.2, 1.5)]
    )

    pipeline.process_audio("call-1", b"a", 0.0, track="outbound", speaker_role=SpeakerRole.ICR)
    pipeline.process_audio("call-1", b"b", 1.0, track="inbound", speaker_role=SpeakerRole.CUSTOMER)

    assert [u.speaker_role for u in workflow.utterances] == [SpeakerRole.ICR, SpeakerRole.CUSTOMER]
    assert diarization.calls == 0
    assert session.role_for("outbound") == SpeakerRole.ICR
    assert session.role_for("inbound") == SpeakerRole.CUSTOMER


def test_speech_transcribed_late_keeps_the_transcript_in_call_order():
    pipeline, workflow, _, _ = _pipeline([("sorry sir", 0.5, 1.0), ("my car", 0.0, 2.0)])

    pipeline.process_audio("call-1", b"a", 3.0, track="outbound", speaker_role=SpeakerRole.ICR)
    # The customer's chunk started earlier but was cut later.
    pipeline.process_audio("call-1", b"b", 2.0, track="inbound", speaker_role=SpeakerRole.CUSTOMER)

    starts = [u.start_time for u in workflow.utterances]
    assert starts == sorted(starts)
    assert workflow.utterances[1].end_time == 4.0


def test_each_track_keeps_its_own_open_utterance():
    pipeline, workflow, _, _ = _pipeline(
        [("I gave my car", 0.0, 1.0), ("okay", 0.0, 0.5), ("on monday", 0.0, 1.0)]
    )

    pipeline.process_audio("call-1", b"a", 0.0, ends_utterance=False, track="inbound", speaker_role=SpeakerRole.CUSTOMER)
    pipeline.process_audio("call-1", b"b", 0.5, track="outbound", speaker_role=SpeakerRole.ICR)
    pipeline.process_audio("call-1", b"c", 1.0, continues_previous=True, track="inbound", speaker_role=SpeakerRole.CUSTOMER)

    # The ICR spoke in between, so the customer's speech could not grow in
    # place; it is a new utterance with the customer's role.
    assert [(u.speaker_role, u.transcript) for u in workflow.utterances] == [
        (SpeakerRole.CUSTOMER, "I gave my car"),
        (SpeakerRole.ICR, "okay"),
        (SpeakerRole.CUSTOMER, "on monday"),
    ]


def test_mixed_audio_learns_the_role_from_the_icr_greeting():
    diarization = _Diarization(
        [
            [seg("SPEAKER_00", ICR_VOICE, 0.0, 2.0)],
            [seg("SPEAKER_00", CUSTOMER_VOICE, 0.0, 2.0)],
            [seg("SPEAKER_01", _near(ICR_VOICE), 0.0, 2.0)],
        ]
    )
    pipeline, workflow, _, _ = _pipeline(
        [
            ("thank you for calling, how may I help you", 0.0, 2.0),
            ("hello, the brakes are noisy", 0.0, 2.0),
            ("let me check that", 0.0, 2.0),
        ],
        diarization,
    )

    for offset in (0.0, 2.0, 4.0):
        pipeline.process_audio("call-1", b"x", offset)

    assert [u.speaker_role for u in workflow.utterances] == [
        SpeakerRole.ICR,
        SpeakerRole.CUSTOMER,
        SpeakerRole.ICR,
    ]


# ---- LiveChunkProcessingService ----

class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def process_audio(self, call_id, audio, start_offset=0.0, **kwargs):
        self.calls.append({"start": start_offset, **kwargs})


def _chunk(sequence, start, track, final=False):
    return AudioChunk(
        sequence=sequence,
        start_time=start,
        end_time=start + 1.0,
        audio=b"x",
        is_final=final,
        track=track,
        speaker_role=SpeakerRole.ICR if track == "outbound" else SpeakerRole.CUSTOMER,
    )


def test_tracks_are_ordered_separately_but_share_one_processor():
    recorder = _Recorder()
    built: list[str] = []
    service = LiveChunkProcessingService(lambda call_id: built.append(call_id) or recorder)

    service.process_chunk("c", _chunk(0, 0.0, "inbound"))
    service.process_chunk("c", _chunk(0, 0.0, "outbound"))
    service.process_chunk("c", _chunk(1, 1.0, "inbound", final=True))

    assert built == ["c"]
    assert [c["track"] for c in recorder.calls] == ["inbound", "outbound", "inbound"]
    assert recorder.calls[1]["speaker_role"] == SpeakerRole.ICR
    assert not service.is_completed("c")
    with pytest.raises(DuplicateChunkError):
        service.process_chunk("c", _chunk(0, 1.0, "outbound"))


# ---- Plivo ----

def _plivo(**overrides) -> PlivoTelephonyProvider:
    return PlivoTelephonyProvider(
        Settings(_env_file=None, plivo_auth_token="t", **overrides)  # type: ignore[call-arg]
    )


def test_stream_response_dials_the_icr_and_streams_both_tracks():
    xml = _plivo(
        plivo_icr_dial_targets="+919800000001, sip:icr2@sip.plivo.com",
        plivo_icr_caller_id="+914400000000",
    ).build_stream_response("wss://x/stream?token=a&b=c").content

    assert 'audioTrack="both"' in xml
    assert 'keepCallAlive="false"' in xml
    assert 'contentType="audio/x-mulaw;rate=8000"' in xml
    assert "wss://x/stream?token=a&amp;b=c</Stream>" in xml
    assert '<Dial callerId="+914400000000" timeout="30">' in xml
    assert "<Number>+919800000001</Number>" in xml
    assert "<User>sip:icr2@sip.plivo.com</User>" in xml
    assert xml.index("<Stream") < xml.index("<Dial")


def test_stream_response_without_an_icr_streams_the_caller_and_holds_the_call():
    xml = _plivo().build_stream_response("wss://x/stream").content

    assert 'keepCallAlive="true"' in xml
    assert 'contentType="audio/x-mulaw;rate=8000"' in xml
    assert "<Dial" not in xml


def test_plivo_events_carry_their_tracks():
    start = parse_plivo_media_stream_event(
        {
            "event": "start",
            "start": {
                "tracks": ["inbound", "outbound"],
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
            },
        }
    )
    media = parse_plivo_media_stream_event(
        {"event": "media", "media": {"track": "outbound", "chunk": 3, "payload": "//8="}}
    )

    assert start.tracks == ("inbound", "outbound")
    assert media.track == "outbound"
    assert media.sequence == 3


# ---- Telephony stream with both tracks, end to end ----

def _tone_b64(samples: int) -> str:
    assert audioop is not None
    pcm = b"".join(
        int(8000 * math.sin(i / 3)).to_bytes(2, "little", signed=True) for i in range(samples)
    )
    return base64.b64encode(audioop.lin2ulaw(pcm, 2)).decode("ascii")


def _silence_b64(samples: int) -> str:
    assert audioop is not None
    return base64.b64encode(audioop.lin2ulaw(b"\x00\x00" * samples, 2)).decode("ascii")


@pytest.mark.skipif(audioop is None, reason="audioop is not installed")
def test_two_track_stream_transcribes_each_side_with_its_role(monkeypatch):
    from tests.test_telephony import (
        _answer_call,
        _build_client,
        _stream_path,
        _wait_for_stream,
    )

    class _TrackASR(ASRProvider):
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, audio: bytes) -> ASRResult:
            self.calls += 1
            return ASRResult(f"line {self.calls}", "en", 0.0, 0.01, 0.9)

    asr = _TrackASR()
    client, services = _build_client(
        monkeypatch,
        asr_provider=asr,
        plivo_stream_flush_seconds=0.01,
        plivo_icr_dial_targets="+919800000001",
    )
    call_id = _answer_call(client, "uuid-two-tracks")

    with client.websocket_connect(_stream_path(call_id)) as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "tracks": ["inbound", "outbound"],
                        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
                    },
                }
            )
        )
        _wait_for_stream(services, "uuid-two-tracks", is_open=True)
        frames = [
            ("outbound", 1, _tone_b64(80)),  # the ICR speaks
            ("inbound", 1, _silence_b64(80)),  # the customer is silent: skipped
            ("inbound", 2, _tone_b64(80)),  # the customer speaks
        ]
        for track, chunk, payload in frames:
            ws.send_text(
                json.dumps(
                    {"event": "media", "media": {"track": track, "chunk": chunk, "payload": payload}}
                )
            )
        ws.send_text(json.dumps({"event": "stop"}))
        _wait_for_stream(services, "uuid-two-tracks", is_open=False)

    utterances = services.call_service.get_call(call_id).utterances
    assert asr.calls == 2
    assert [u.speaker_role for u in utterances] == [SpeakerRole.ICR, SpeakerRole.CUSTOMER]


# ---- Silence and the live analysis schedule ----

def test_silence_is_reported_as_no_speech_not_as_a_failure():
    from app.ai.asr.provider import NoSpeechDetected
    from app.ai.asr.sarvam_provider import SarvamASRError, SarvamASRProvider

    for payload in ({"transcript": "", "language_code": None}, {"language_code": "en-IN"}):
        with pytest.raises(NoSpeechDetected) as raised:
            SarvamASRProvider._to_result(payload)
        assert isinstance(raised.value, SarvamASRError)


def test_follow_up_analysis_waits_for_the_minimum_interval():
    from concurrent.futures import Executor, Future

    from app.services.live_analysis_scheduler import LiveAnalysisScheduler

    class Inline(Executor):
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return Future()

    slept: list[float] = []
    runs: list[str] = []

    class Workflow:
        def analyze_latest_speech(self, call_id):
            runs.append(call_id)
            if len(runs) == 1:
                scheduler.request_analysis(call_id)  # speech arrived meanwhile

    scheduler = LiveAnalysisScheduler(
        Workflow(), executor=Inline(), min_interval_seconds=5.0, sleep=slept.append
    )
    scheduler.request_analysis("c")

    assert runs == ["c", "c"]
    assert len(slept) == 1 and 4.0 < slept[0] <= 5.0
