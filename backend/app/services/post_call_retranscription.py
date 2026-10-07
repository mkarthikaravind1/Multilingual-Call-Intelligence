import audioop
import io
import logging
import wave
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import uuid4

from app.ai.asr.provider import ASRProvider, ASRResult, NoSpeechDetected, TimedText
from app.ai.language.provider import LanguageIdentificationProvider
from app.domain.conversation import Conversation
from app.domain.customer_language import main_indic_language
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_recording_store import CallRecordingStore

logger = logging.getLogger(__name__)

# As the live stream assigns them (see app.api.v1.telephony_ws): the caller
# is the customer, the dialled party the ICR.
_TRACK_ROLES: dict[str, SpeakerRole] = {
    "inbound": SpeakerRole.CUSTOMER,
    "outbound": SpeakerRole.ICR,
}
_FRAME_SECONDS = 0.02
_LEAD_IN_FRAMES = 10  # 0.2 s


@dataclass(frozen=True)
class _Window:
    track: str | None
    role: SpeakerRole | None
    language_hint: str | None
    start_time: float
    audio: bytes  # WAV


class PostCallRetranscriptionService:
    """Transcribes a finished call again from its recording.

    Live, the ASR hears a few seconds at a time, so it often mishears words
    and the language, above all in Tamil and code-mixed speech. Here each
    speaker's audio is cut into windows of up to window_seconds (at the
    quietest point, so words are not cut in half) and transcribed with that
    speaker's language, as the live transcript found it.

    Returns the new utterances in call order, or None to keep the live
    transcript: no recording of the call, no speech heard, or any window
    failing (a partial transcript would lose speech the live one has).
    """

    def __init__(
        self,
        asr_provider: ASRProvider,
        language_provider: LanguageIdentificationProvider,
        recording_store: CallRecordingStore,
        window_seconds: float = 25.0,
        workers: int = 4,
        silence_rms: int = 350,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        if window_seconds <= 1:
            raise ValueError("window_seconds must be more than 1 second.")
        self._asr_provider = asr_provider
        self._language_provider = language_provider
        self._recording_store = recording_store
        self._window_seconds = window_seconds
        self._workers = max(1, workers)
        self._silence_rms = silence_rms
        self._id_factory = id_factory

    def retranscribe(self, conversation: Conversation) -> tuple[Utterance, ...] | None:
        recording = self._recording_store.take(conversation.call_id)
        if recording is None:
            return None
        if recording.truncated:
            logger.info(
                "Recording of call %r was cut at its length limit; keeping the live transcript",
                conversation.call_id,
            )
            return None

        windows: list[_Window] = []
        for track, pcm in recording.tracks.items():
            role = _TRACK_ROLES.get(track) if track is not None else None
            hint = self._language_hint(conversation.utterances, role)
            for start, end in _speech_windows(
                bytes(pcm), recording.sample_rate, self._window_seconds, self._silence_rms
            ):
                windows.append(
                    _Window(
                        track=track,
                        role=role,
                        language_hint=hint,
                        start_time=start / (2 * recording.sample_rate),
                        audio=_wav(bytes(pcm[start:end]), recording.sample_rate),
                    )
                )
        if not windows:
            return None

        live = conversation.utterances
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            results = list(pool.map(lambda w: self._transcribe_window(w, live), windows))

        utterances = sorted(
            (utterance for result in results for utterance in result),
            key=lambda utterance: utterance.start_time,
        )
        if not utterances:
            return None
        logger.info(
            "Transcribed call %r again from %d windows: %d utterances (live: %d)",
            conversation.call_id,
            len(windows),
            len(utterances),
            len(live),
        )
        return tuple(utterances)

    def _language_hint(
        self, utterances: tuple[Utterance, ...], role: SpeakerRole | None
    ) -> str | None:
        if not self._asr_provider.supports_language_hint:
            return None
        if role is not None:
            utterances = tuple(u for u in utterances if u.speaker_role == role)
        return main_indic_language(utterances)

    def _transcribe_window(
        self, window: _Window, live: tuple[Utterance, ...]
    ) -> list[Utterance]:
        try:
            if window.language_hint is None:
                result = self._asr_provider.transcribe(window.audio)
            else:
                result = self._asr_provider.transcribe(
                    window.audio, language_hint=window.language_hint
                )
        except NoSpeechDetected:
            return []

        utterances: list[Utterance] = []
        for item in _timed_items(result):
            start = window.start_time + item.start_time
            end = max(start, window.start_time + item.end_time)
            utterances.append(
                Utterance(
                    utterance_id=self._id_factory(),
                    transcript=item.text.strip(),
                    speaker_role=window.role or _live_role(live, start, end),
                    languages=self._languages(item.text, result.detected_language),
                    start_time=start,
                    end_time=end,
                    confidence=result.confidence,
                )
            )
        return utterances

    def _languages(self, text: str, detected_language: str) -> tuple[str, ...]:
        try:
            spans = self._language_provider.identify(text).languages
        except Exception:
            logger.warning("Language identification failed; using the ASR's language")
            return (detected_language,)
        codes = tuple(dict.fromkeys(span.language for span in spans))
        return codes or (detected_language,)


def _timed_items(result: ASRResult) -> list[TimedText]:
    items = [item for item in result.timed_text if item.text.strip()]
    if items:
        return items
    if not result.transcript.strip():
        return []
    return [TimedText(result.transcript, result.start_time, result.end_time)]


def _live_role(live: tuple[Utterance, ...], start: float, end: float) -> SpeakerRole:
    """Mixed audio: the role of the live utterance this speech overlaps most."""
    best, best_overlap = SpeakerRole.UNKNOWN, 0.0
    for utterance in live:
        overlap = min(end, utterance.end_time) - max(start, utterance.start_time)
        if overlap > best_overlap:
            best, best_overlap = utterance.speaker_role, overlap
    return best


def _speech_windows(
    pcm: bytes, sample_rate: int, window_seconds: float, silence_rms: int
) -> list[tuple[int, int]]:
    """Byte ranges of pcm, each up to window_seconds long, that hold speech.
    A window ends in the middle of the longest pause in its second half, or
    at the length limit when it has no pause."""
    frame_bytes = int(sample_rate * _FRAME_SECONDS) * 2
    if frame_bytes <= 0 or not pcm:
        return []
    loud = [
        audioop.rms(pcm[i : i + frame_bytes], 2) >= silence_rms
        for i in range(0, len(pcm) - len(pcm) % 2, frame_bytes)
    ]
    max_frames = max(1, int(window_seconds / _FRAME_SECONDS))

    windows: list[tuple[int, int]] = []
    position = 0
    while position < len(loud):
        # Skip the silence before the speech (keeping a short lead-in).
        first_loud = next((i for i in range(position, len(loud)) if loud[i]), None)
        if first_loud is None:
            break
        position = max(position, first_loud - _LEAD_IN_FRAMES)
        end = min(position + max_frames, len(loud))
        if end < len(loud):
            end = _cut_point(loud, position + max_frames // 2, end)
        if any(loud[position:end]):
            windows.append((position * frame_bytes, min(end * frame_bytes, len(pcm))))
        position = end
    return windows


def _cut_point(loud: list[bool], first: int, limit: int) -> int:
    best_start, best_length = None, 0
    run_start = None
    for index in range(first, limit + 1):
        quiet = index < limit and not loud[index]
        if quiet and run_start is None:
            run_start = index
        elif not quiet and run_start is not None:
            if index - run_start > best_length:
                best_start, best_length = run_start, index - run_start
            run_start = None
    if best_start is None:
        return limit
    return best_start + best_length // 2 or limit


def _wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm)
    return buffer.getvalue()
