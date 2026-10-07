import math
from typing import Any
import httpx
from app.ai.asr.provider import ASRProvider, ASRResult
from app.core.config import Settings, get_settings
from app.core.constants import SUPPORTED_LANGUAGES
from app.ai.asr.provider import ASRProvider, ASRResult, NoSpeechDetected, TimedText
import re

_ENDPOINT_PATH = "/speech-to-text"
_UNCONFIGURED = "not_configured"
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.?!।])\s+")

class SarvamASRError(Exception):
    pass


class SarvamNoSpeechError(SarvamASRError, NoSpeechDetected):
    """Sarvam heard no speech in the audio."""

class SarvamASRProvider(ASRProvider):
    supports_language_hint = True

    def __init__(
        self, settings: Settings | None = None, client: httpx.Client | None = None
    ) -> None:
        settings = settings or get_settings()
        api_key = settings.sarvam_api_key.strip()
        base_url = settings.sarvam_base_url.strip().rstrip("/")
        model = settings.sarvam_stt_model.strip()

        if not api_key or api_key == _UNCONFIGURED:
            raise SarvamASRError("Sarvam API key is not configured.")
        if not base_url or not model:
            raise SarvamASRError("Sarvam base URL and model must be configured.")

        self._api_key = api_key
        self._url = f"{base_url}{_ENDPOINT_PATH}"
        self._model = model
        self._mode = (settings.sarvam_stt_mode or "").strip() or None
        self._audio_codec = (settings.sarvam_input_audio_codec or "").strip() or None
        self._client = client or httpx.Client(timeout=settings.sarvam_timeout_seconds)

    def transcribe(self, audio: bytes, language_hint: str | None = None) -> ASRResult:
        if not audio:
            raise SarvamASRError("audio must not be empty.")
        if language_hint is not None and language_hint not in SUPPORTED_LANGUAGES:
            raise SarvamASRError(f"Unsupported language hint {language_hint!r}.")
        return self._to_result(self._post(audio, language_hint), language_hint)

    def _post(self, audio: bytes, language_hint: str | None = None) -> Any:
        form = {
            "model": self._model,
            # A known language spares Sarvam guessing it from a few seconds
            # of audio; codemix mode still keeps the English words.
            "language_code": f"{language_hint}-IN" if language_hint else "unknown",
            "with_timestamps": "true",
        }
        if self._mode:
            form["mode"] = self._mode
        if self._audio_codec:
            form["input_audio_codec"] = self._audio_codec

        try:
            response = self._client.post(
                self._url,
                headers={"api-subscription-key": self._api_key},
                data=form,
                files={"file": ("audio", audio, "application/octet-stream")},
            )
        except httpx.HTTPError as exc:
            raise SarvamASRError(
                f"Sarvam request failed ({type(exc).__name__})."
            ) from exc

        if response.status_code != 200:
            raise SarvamASRError(
                f"Sarvam returned HTTP {response.status_code}."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise SarvamASRError("Sarvam returned a non-JSON response.") from exc

    @staticmethod
    def _to_result(payload: Any, language_hint: str | None = None) -> ASRResult:
        if not isinstance(payload, dict):
            raise SarvamASRError("Sarvam response is not a JSON object.")

        transcript = payload.get("transcript")
        if not isinstance(transcript, str) or not transcript.strip():
            raise SarvamNoSpeechError("Sarvam response has no transcript.")

        timestamps = payload.get("timestamps")
        start_time, end_time = _extract_time_range(timestamps)
        return ASRResult(
            transcript=transcript,
            detected_language=_map_language(payload.get("language_code"), language_hint),
            start_time=start_time,
            end_time=end_time,
            confidence=None,
            timed_text=_extract_timed_text(timestamps),
        )


def _map_language(code: Any, language_hint: str | None = None) -> str:
    if not isinstance(code, str) or not code.strip():
        # Sarvam may leave it out when it was told the language.
        if language_hint is not None:
            return language_hint
        raise SarvamASRError("Sarvam response has no language_code.")
    language = code.strip().split("-")[0].lower()
    if language not in SUPPORTED_LANGUAGES:
        raise SarvamASRError(f"Sarvam returned unsupported language {code[:20]!r}.")
    return language


def _extract_time_range(timestamps: Any) -> tuple[float, float]:
    if not isinstance(timestamps, dict):
        raise SarvamASRError("Sarvam response has no timestamps.")

    starts = timestamps.get("start_time_seconds")
    ends = timestamps.get("end_time_seconds")
    if (
        not isinstance(starts, list)
        or not isinstance(ends, list)
        or not starts
        or len(starts) != len(ends)
        or not all(_is_valid_time(value) for value in (*starts, *ends))
        or any(end < start for start, end in zip(starts, ends))
    ):
        raise SarvamASRError("Sarvam timestamps are malformed.")

    return float(min(starts)), float(max(ends))

def _extract_timed_text(timestamps: Any) -> tuple[TimedText, ...]:
    words = timestamps.get("words")
    starts = timestamps["start_time_seconds"]
    ends = timestamps["end_time_seconds"]
    if (
        not isinstance(words, list)
        or len(words) != len(starts)
        or not all(isinstance(word, str) for word in words)
    ):
        return ()
    items: list[TimedText] = []
    for word, start, end in zip(words, starts, ends):
        if word.strip():
            items.extend(_split_chunk(word, float(start), float(end)))
    return tuple(items)


def _split_chunk(text: str, start: float, end: float) -> list[TimedText]:
    sentences = [s for s in _SENTENCE_BOUNDARY.split(text.strip()) if s]
    if len(sentences) <= 1 or end <= start:
        return [TimedText(text=text, start_time=start, end_time=end)]

    total = sum(len(s) for s in sentences)
    span = end - start
    items: list[TimedText] = []
    cursor = start
    consumed = 0
    for index, sentence in enumerate(sentences):
        consumed += len(sentence)
        sentence_end = (
            end if index == len(sentences) - 1 else start + span * consumed / total
        )
        items.append(TimedText(text=sentence, start_time=cursor, end_time=sentence_end))
        cursor = sentence_end
    return items

def _is_valid_time(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )