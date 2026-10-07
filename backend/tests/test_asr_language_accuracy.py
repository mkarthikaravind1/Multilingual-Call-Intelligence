"""Tamil and code-mixed transcription: the language lock, 16 kHz L16 audio
from Plivo, and transcribing the call again from its recording afterwards."""

import base64
import io
import math
import struct
import wave

import httpx
import pytest

from app.ai.asr.provider import ASRProvider, ASRResult, NoSpeechDetected, TimedText
from app.ai.asr.sarvam_provider import SarvamASRProvider
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRoleAssignment,
    SpeakerRole as AISpeakerRole,
)
from app.core.config import Settings
from app.domain.conversation import Conversation, ConversationStatus
from app.domain.utterance import SpeakerRole, Utterance
from app.services.audio_processing_pipeline import AudioProcessingPipeline
from app.services.call_recording_store import CallRecording, CallRecordingStore
from app.services.language_lock import LanguageLock
from app.services.post_call_retranscription import (
    PostCallRetranscriptionService,
    _speech_windows,
)
from app.telephony.plivo.audio import L16, decode_media_payload
from app.telephony.plivo.provider import PlivoTelephonyProvider, parse_plivo_media_stream_event
from app.telephony.provider import TelephonyStreamError

RATE = 16000


def _tone(seconds: float, amplitude: int = 8000) -> bytes:
    samples = int(seconds * RATE)
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(i / 5))) for i in range(samples)
    )


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * RATE)


def _wav_seconds(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio)) as source:
        return source.getnframes() / source.getframerate()


# --- Sarvam language hint ---


def _sarvam(captured: list[httpx.Request], payload: dict) -> SarvamASRProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload)

    settings = Settings.model_construct(
        sarvam_api_key="k",
        sarvam_base_url="https://sarvam.test",
        sarvam_stt_model="saaras:v3",
        sarvam_stt_mode="codemix",
        sarvam_timeout_seconds=5.0,
        sarvam_input_audio_codec=None,
    )
    return SarvamASRProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_sarvam_is_told_a_known_language():
    captured: list[httpx.Request] = []
    payload = {
        "transcript": "வணக்கம்",
        "language_code": None,
        "timestamps": {"words": ["வணக்கம்"], "start_time_seconds": [0.1], "end_time_seconds": [0.9]},
    }

    result = _sarvam(captured, payload).transcribe(b"audio", language_hint="ta")

    assert b'name="language_code"\r\n\r\nta-IN' in captured[0].content
    assert b'name="mode"\r\n\r\ncodemix' in captured[0].content
    # Sarvam may leave the language out when it was told it.
    assert result.detected_language == "ta"


# --- Language lock ---


def test_lock_after_two_chunks_in_the_same_indian_language():
    lock = LanguageLock(lock_after=2)
    lock.observe("inbound", "ta")
    assert lock.hint("inbound") is None
    lock.observe("inbound", "en")  # English words do not break the run
    lock.observe("inbound", "ta")
    assert lock.hint("inbound") == "ta"
    assert lock.hint("outbound") is None


def test_english_never_locks_and_a_different_language_restarts_the_run():
    lock = LanguageLock(lock_after=2)
    for language in ("en", "en", "ta", "ml"):
        lock.observe(None, language)
    assert lock.hint(None) is None


def test_lock_is_released_by_empty_or_other_language_speech():
    lock = LanguageLock(lock_after=1, unlock_after=2)
    lock.observe(None, "ta")
    lock.observe_no_speech(None)
    lock.observe(None, "ta")  # heard fine again: the miss count restarts
    lock.observe_no_speech(None)
    assert lock.hint(None) == "ta"
    lock.observe(None, "te")
    assert lock.hint(None) is None


def test_lock_after_zero_turns_locking_off():
    lock = LanguageLock(lock_after=0)
    lock.observe(None, "ta")
    lock.observe(None, "ta")
    assert lock.hint(None) is None


class HintedASR(ASRProvider):
    supports_language_hint = True

    def __init__(self) -> None:
        self.hints: list[str | None] = []

    def transcribe(self, audio, language_hint=None):
        self.hints.append(language_hint)
        return ASRResult("வணக்கம் சார்", language_hint or "ta", 0.0, 1.0, None)


class TextLanguage(LanguageIdentificationProvider):
    def identify(self, text):
        return LanguageIdentificationResult([LanguageSpan("ta", 0.9)])


class NoDiarization(DiarizationProvider):
    def diarize(self, audio):
        return [DiarizedSegment("S", 0.0, 1.0)]


class NoRoles(RoleIdentificationProvider):
    def identify_roles(self, segments):
        return [SpeakerRoleAssignment("S", AISpeakerRole.UNKNOWN)]


class StoreUtterances:
    def __init__(self) -> None:
        self.utterances: list[Utterance] = []

    def process_utterance(self, call_id, utterance):
        self.utterances.append(utterance)

    def process_utterance_update(self, call_id, utterance):
        self.utterances[-1] = utterance


def test_live_pipeline_tells_the_asr_the_locked_language_per_track():
    asr = HintedASR()
    pipeline = AudioProcessingPipeline(
        asr, TextLanguage(), NoDiarization(), NoRoles(), StoreUtterances(),
        language_lock=LanguageLock(lock_after=2),
    )

    for start in range(3):
        pipeline.process_audio(
            "c", b"x", float(start), track="inbound", speaker_role=SpeakerRole.CUSTOMER
        )
    pipeline.process_audio("c", b"x", 3.0, track="outbound", speaker_role=SpeakerRole.ICR)

    assert asr.hints == [None, None, "ta", None]


def test_providers_without_hints_are_called_as_before():
    class PlainASR(ASRProvider):
        def transcribe(self, audio):
            return ASRResult("வணக்கம்", "ta", 0.0, 1.0, None)

    pipeline = AudioProcessingPipeline(
        PlainASR(), TextLanguage(), NoDiarization(), NoRoles(), StoreUtterances(),
        language_lock=LanguageLock(lock_after=1),
    )
    for start in range(3):
        pipeline.process_audio("c", b"x", float(start))


# --- Plivo 16 kHz linear PCM ---


def _plivo(**overrides) -> PlivoTelephonyProvider:
    return PlivoTelephonyProvider(
        Settings(_env_file=None, plivo_auth_token="t", **overrides)  # type: ignore[call-arg]
    )


def test_plivo_streams_16khz_linear_pcm_by_default():
    xml = _plivo().build_stream_response("wss://x/stream").content
    assert 'contentType="audio/x-l16;rate=16000"' in xml


def test_plivo_stream_audio_can_go_back_to_mulaw():
    xml = _plivo(plivo_stream_audio="mulaw_8k").build_stream_response("wss://x/s").content
    assert 'contentType="audio/x-mulaw;rate=8000"' in xml


def test_l16_stream_frames_are_decoded_as_pcm():
    start = parse_plivo_media_stream_event(
        {"event": "start", "start": {"mediaFormat": {"encoding": "audio/x-l16", "sampleRate": 16000}}}
    )
    pcm = struct.pack("<4h", 0, 1000, -1000, 32000)
    media = parse_plivo_media_stream_event(
        {"event": "media", "media": {"payload": base64.b64encode(pcm).decode()}},
        start.encoding,
    )

    assert (start.encoding, start.sample_rate) == (L16, 16000)
    assert media.audio == pcm


def test_odd_sized_l16_payload_is_rejected():
    with pytest.raises(TelephonyStreamError):
        parse_plivo_media_stream_event(
            {"event": "media", "media": {"payload": base64.b64encode(b"abc").decode()}}, L16
        )


def test_mulaw_stays_the_default_decoding():
    mulaw = base64.b64encode(b"\xff" * 160).decode()
    assert len(decode_media_payload(mulaw)) == 320


# --- Recording store ---


def test_recordings_are_taken_once_and_expire():
    now = [0.0]
    store = CallRecordingStore(max_calls=2, ttl_seconds=10, clock=lambda: now[0])
    for call in ("a", "b", "c"):
        store.put(call, CallRecording(sample_rate=RATE, max_seconds=60))

    assert store.take("a") is None  # only the newest two are kept
    assert store.take("b") is not None
    assert store.take("b") is None
    now[0] = 11.0
    assert store.take("c") is None


def test_recording_is_cut_at_its_length_limit():
    recording = CallRecording(sample_rate=RATE, max_seconds=1.0)
    recording.append("inbound", _tone(1.5))
    assert recording.duration("inbound") == 1.0
    assert recording.truncated


# --- Transcribing the call again ---


def test_windows_skip_silence_and_cut_in_pauses():
    pcm = _tone(10) + _silence(1) + _tone(10) + _silence(5)
    windows = _speech_windows(pcm, RATE, window_seconds=15.0, silence_rms=350)

    seconds = [(s / (2 * RATE), e / (2 * RATE)) for s, e in windows]
    assert len(seconds) == 2
    first_end = seconds[0][1]
    assert 10.0 <= first_end <= 11.0  # in the pause, not inside the speech
    # The next window starts just before the speech, after the pause.
    assert first_end < seconds[1][0] <= 11.0


class WindowASR(ASRProvider):
    supports_language_hint = True

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[float, str | None]] = []
        self._fail = fail

    def transcribe(self, audio, language_hint=None):
        if self._fail:
            raise RuntimeError("ASR down")
        self.calls.append((_wav_seconds(audio), language_hint))
        return ASRResult(
            "முதல். இரண்டு.",
            language_hint or "ta",
            0.5,
            2.0,
            None,
            timed_text=(TimedText("முதல்.", 0.5, 1.0), TimedText("இரண்டு.", 1.0, 2.0)),
        )


def _completed_call(*utterances: Utterance) -> Conversation:
    conversation = Conversation(call_id="call-1")
    for utterance in utterances:
        conversation.add_utterance(utterance)
    conversation.complete(30.0)
    return conversation


def _live(role: SpeakerRole, start: float, language: str = "ta") -> Utterance:
    return Utterance(f"live-{role.value}-{start}", "live", role, (language,), start, start + 2)


def _service(asr: ASRProvider, store: CallRecordingStore) -> PostCallRetranscriptionService:
    return PostCallRetranscriptionService(
        asr, TextLanguage(), store, window_seconds=25.0, workers=2
    )


def test_call_is_transcribed_again_per_track_in_each_speakers_language():
    store = CallRecordingStore()
    recording = CallRecording(sample_rate=RATE, max_seconds=600)
    recording.append("inbound", _tone(3))
    recording.append("outbound", _silence(5) + _tone(3))
    store.put("call-1", recording)
    asr = WindowASR()
    call = _completed_call(
        _live(SpeakerRole.CUSTOMER, 0.0, "ta"), _live(SpeakerRole.ICR, 5.0, "en")
    )

    utterances = _service(asr, store).retranscribe(call)

    assert utterances is not None
    assert {hint for _, hint in asr.calls} == {None, "ta"}
    assert [(u.speaker_role, u.transcript, u.start_time) for u in utterances] == [
        (SpeakerRole.CUSTOMER, "முதல்.", 0.5),
        (SpeakerRole.CUSTOMER, "இரண்டு.", 1.0),
        # The window starts 0.2 s before the ICR speaks at 5 s.
        (SpeakerRole.ICR, "முதல்.", pytest.approx(5.3)),
        (SpeakerRole.ICR, "இரண்டு.", pytest.approx(5.8)),
    ]
    assert store.take("call-1") is None  # used once


def test_mixed_audio_takes_roles_from_the_live_transcript():
    store = CallRecordingStore()
    recording = CallRecording(sample_rate=RATE, max_seconds=600)
    recording.append(None, _tone(3))
    store.put("call-1", recording)

    utterances = _service(WindowASR(), store).retranscribe(
        _completed_call(_live(SpeakerRole.ICR, 0.0))
    )

    assert utterances is not None
    assert {u.speaker_role for u in utterances} == {SpeakerRole.ICR}


@pytest.mark.parametrize("recorded", [False, True])
def test_live_transcript_is_kept_without_a_recording_or_on_failure(recorded):
    store = CallRecordingStore()
    if recorded:
        recording = CallRecording(sample_rate=RATE, max_seconds=600)
        recording.append("inbound", _tone(3))
        store.put("call-1", recording)
    service = _service(WindowASR(fail=True), store)
    call = _completed_call(_live(SpeakerRole.CUSTOMER, 0.0))

    if recorded:
        with pytest.raises(RuntimeError):
            service.retranscribe(call)
    else:
        assert service.retranscribe(call) is None


def test_silent_windows_give_no_transcript():
    class Silent(WindowASR):
        def transcribe(self, audio, language_hint=None):
            raise NoSpeechDetected()

    store = CallRecordingStore()
    recording = CallRecording(sample_rate=RATE, max_seconds=600)
    recording.append("inbound", _tone(3))
    store.put("call-1", recording)

    assert _service(Silent(), store).retranscribe(_completed_call()) is None


def test_completed_call_transcript_can_be_replaced():
    call = _completed_call(_live(SpeakerRole.CUSTOMER, 0.0))
    revised = (_live(SpeakerRole.CUSTOMER, 0.5), _live(SpeakerRole.ICR, 1.0))

    call.replace_transcript(revised)

    assert call.utterances == revised
    assert call.status == ConversationStatus.COMPLETED
    with pytest.raises(ValueError):
        call.replace_transcript(tuple(reversed(revised)))
