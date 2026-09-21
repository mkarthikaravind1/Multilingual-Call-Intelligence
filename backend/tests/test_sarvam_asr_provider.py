import ast
from pathlib import Path

import httpx
import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.asr.sarvam_provider import SarvamASRError, SarvamASRProvider
from app.core.config import Settings
from app.services import audio_processing_pipeline, call_workflow_service
from app.ai.asr.provider import ASRProvider
from app.ai.asr.sarvam_provider import SarvamASRError, SarvamASRProvider
from app.composition.providers import UnsupportedProviderError, create_asr_provider
from app.composition import providers
from app.ai.asr.provider import ASRProvider, ASRResult, TimedText

AUDIO = b"fake-audio-bytes"
API_KEY = "test-key"


def _settings(**overrides) -> Settings:
    values = {
        "sarvam_api_key": API_KEY,
        "sarvam_base_url": "https://sarvam.test",
        "sarvam_stt_model": "saaras:v3",
        "sarvam_timeout_seconds": 5.0,
        "sarvam_input_audio_codec": None,
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def _payload(**overrides) -> dict:
    payload = {
        "request_id": "req-1",
        "transcript": "வணக்கம் சார்",
        "language_code": "ta-IN",
        "timestamps": {
            "words": ["வணக்கம் சார்"],
            "start_time_seconds": [0.4],
            "end_time_seconds": [2.1],
        },
    }
    payload.update(overrides)
    return payload


def _without(key: str) -> dict:
    payload = _payload()
    del payload[key]
    return payload


def _timestamps(starts, ends) -> dict:
    return {"start_time_seconds": starts, "end_time_seconds": ends}


def _respond_with(body, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


def _provider(handler, **settings_overrides) -> SarvamASRProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SarvamASRProvider(_settings(**settings_overrides), client=client)


def _capture(captured: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_payload())

    return handler


def test_provider_satisfies_asr_provider_contract():
    provider = _provider(_respond_with(_payload()))

    assert isinstance(provider, ASRProvider)
    assert isinstance(provider.transcribe(AUDIO), ASRResult)


def test_successful_transcription_maps_to_asr_result():
    result = _provider(_respond_with(_payload())).transcribe(AUDIO)

    assert result.transcript == "வணக்கம் சார்"
    assert result.detected_language == "ta"
    assert (result.start_time, result.end_time) == (0.4, 2.1)
    assert result.confidence is None


def test_request_is_built_from_settings():
    captured: list[httpx.Request] = []

    _provider(_capture(captured)).transcribe(AUDIO)

    request = captured[0]
    assert request.method == "POST"
    assert str(request.url) == "https://sarvam.test/speech-to-text"
    assert request.headers["api-subscription-key"] == API_KEY
    assert b'name="model"\r\n\r\nsaaras:v3' in request.content
    assert b'name="language_code"\r\n\r\nunknown' in request.content
    assert b'name="with_timestamps"\r\n\r\ntrue' in request.content
    assert AUDIO in request.content
    assert b"input_audio_codec" not in request.content


def test_configured_audio_codec_is_sent():
    captured: list[httpx.Request] = []

    _provider(_capture(captured), sarvam_input_audio_codec="pcm_s16le").transcribe(AUDIO)

    assert b'name="input_audio_codec"\r\n\r\npcm_s16le' in captured[0].content


def test_trailing_slash_in_base_url_is_normalised():
    captured: list[httpx.Request] = []

    _provider(_capture(captured), sarvam_base_url="https://sarvam.test/").transcribe(AUDIO)

    assert str(captured[0].url) == "https://sarvam.test/speech-to-text"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ta-IN", "ta"),
        ("en-IN", "en"),
        ("te-IN", "te"),
        ("kn-IN", "kn"),
        ("ml-IN", "ml"),
        ("EN-in", "en"),
    ],
)
def test_language_code_is_mapped_to_supported_language(code, expected):
    provider = _provider(_respond_with(_payload(language_code=code)))

    assert provider.transcribe(AUDIO).detected_language == expected


def test_timestamps_span_all_segments():
    payload = _payload(timestamps=_timestamps([0.5, 2, 4.0], [1.8, 3, 5.5]))

    result = _provider(_respond_with(payload)).transcribe(AUDIO)

    assert (result.start_time, result.end_time) == (0.5, 5.5)


MALFORMED_PAYLOADS = {
    "not_an_object": ["transcript"],
    "missing_transcript": _without("transcript"),
    "transcript_not_string": _payload(transcript=123),
    "empty_transcript": _payload(transcript=""),
    "blank_transcript": _payload(transcript="   "),
    "missing_language": _without("language_code"),
    "null_language": _payload(language_code=None),
    "blank_language": _payload(language_code=" "),
    "unsupported_language": _payload(language_code="hi-IN"),
    "missing_timestamps": _without("timestamps"),
    "null_timestamps": _payload(timestamps=None),
    "timestamps_not_object": _payload(timestamps=[1, 2]),
    "missing_start_list": _payload(timestamps={"end_time_seconds": [1.0]}),
    "empty_lists": _payload(timestamps=_timestamps([], [])),
    "mismatched_lengths": _payload(timestamps=_timestamps([0.1, 0.5], [1.0])),
    "non_numeric_time": _payload(timestamps=_timestamps(["a"], [1.0])),
    "boolean_time": _payload(timestamps=_timestamps([True], [1.0])),
    "negative_time": _payload(timestamps=_timestamps([-1.0], [1.0])),
    "end_before_start": _payload(timestamps=_timestamps([2.0], [1.0])),
}


@pytest.mark.parametrize(
    "body", MALFORMED_PAYLOADS.values(), ids=MALFORMED_PAYLOADS.keys()
)
def test_malformed_responses_raise_provider_error(body):
    with pytest.raises(SarvamASRError):
        _provider(_respond_with(body)).transcribe(AUDIO)


@pytest.mark.parametrize("content", [b"<html>oops</html>", b""])
def test_non_json_response_raises_provider_error(content):
    def handler(request):
        return httpx.Response(200, content=content)

    with pytest.raises(SarvamASRError):
        _provider(handler).transcribe(AUDIO)


def test_non_finite_timestamps_raise_provider_error():
    body = (
        b'{"transcript": "hi", "language_code": "en-IN", "timestamps": '
        b'{"start_time_seconds": [NaN], "end_time_seconds": [1.0]}}'
    )

    def handler(request):
        return httpx.Response(200, content=body)

    with pytest.raises(SarvamASRError):
        _provider(handler).transcribe(AUDIO)


@pytest.mark.parametrize("status", [400, 403, 422, 429, 500, 503])
def test_http_errors_become_provider_error_without_leaking_details(status):
    body = {"error": {"message": "internal-detail", "code": "x", "request_id": "r"}}

    with pytest.raises(SarvamASRError) as exc_info:
        _provider(_respond_with(body, status)).transcribe(AUDIO)

    message = str(exc_info.value)
    assert str(status) in message
    assert "internal-detail" not in message
    assert API_KEY not in message


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("boom"),
        httpx.ReadTimeout("boom"),
        httpx.RemoteProtocolError("boom"),
    ],
    ids=["connect", "timeout", "protocol"],
)
def test_network_errors_become_provider_error(error):
    def handler(request):
        raise error

    with pytest.raises(SarvamASRError) as exc_info:
        _provider(handler).transcribe(AUDIO)

    assert "boom" not in str(exc_info.value)
    assert exc_info.value.__cause__ is error


@pytest.mark.parametrize("key", ["not_configured", "", "   "])
def test_missing_api_key_is_rejected(key):
    with pytest.raises(SarvamASRError, match="API key"):
        SarvamASRProvider(_settings(sarvam_api_key=key))


@pytest.mark.parametrize(
    "overrides", [{"sarvam_base_url": ""}, {"sarvam_stt_model": "  "}]
)
def test_incomplete_configuration_is_rejected(overrides):
    with pytest.raises(SarvamASRError, match="configured"):
        SarvamASRProvider(_settings(**overrides))


def test_empty_audio_is_rejected_without_calling_sarvam():
    captured: list[httpx.Request] = []

    with pytest.raises(SarvamASRError):
        _provider(_capture(captured)).transcribe(b"")

    assert captured == []


def _imported_modules(module) -> list[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    names += [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    return names


@pytest.mark.parametrize("module", [audio_processing_pipeline, call_workflow_service])
def test_application_layer_does_not_import_sarvam_or_http_client(module):
    imported = [name.lower() for name in _imported_modules(module)]

    assert not any("sarvam" in name or "httpx" in name for name in imported)

class FakeSarvamASRProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


def test_create_asr_provider_builds_sarvam_from_settings(monkeypatch):
    monkeypatch.setattr(providers, "SarvamASRProvider", FakeSarvamASRProvider)
    settings = Settings.model_construct(asr_provider="SARVAM")

    provider = create_asr_provider(settings)

    assert isinstance(provider, FakeSarvamASRProvider)
    assert provider.settings is settings


@pytest.mark.parametrize("name", ["not_configured", "unknown"])
def test_create_asr_provider_rejects_unsupported_provider(name):
    with pytest.raises(UnsupportedProviderError, match=name):
        create_asr_provider(Settings.model_construct(asr_provider=name))


def test_create_asr_provider_returns_real_sarvam_provider_without_network():
    settings = Settings.model_construct(
        asr_provider="sarvam", sarvam_api_key="test-key"
    )

    provider = create_asr_provider(settings)

    assert isinstance(provider, SarvamASRProvider)
    assert isinstance(provider, ASRProvider)


def test_create_asr_provider_fails_fast_when_api_key_missing():
    settings = Settings.model_construct(asr_provider="sarvam")

    with pytest.raises(SarvamASRError, match="API key"):
        create_asr_provider(settings)

def _timed_payload(words) -> dict:
    return _payload(
        timestamps={
            "words": words,
            "start_time_seconds": [0.4, 1.2],
            "end_time_seconds": [1.1, 2.1],
        }
    )


def test_result_exposes_timed_text():
    result = _provider(_respond_with(_timed_payload(["vanakkam", "sir"]))).transcribe(
        AUDIO
    )

    assert result.timed_text == (
        TimedText("vanakkam", 0.4, 1.1),
        TimedText("sir", 1.2, 2.1),
    )
    assert (result.start_time, result.end_time) == (0.4, 2.1)


def test_missing_words_gives_empty_timed_text():
    payload = _payload(timestamps=_timestamps([0.4], [2.1]))

    result = _provider(_respond_with(payload)).transcribe(AUDIO)

    assert result.timed_text == ()
    assert (result.start_time, result.end_time) == (0.4, 2.1)


@pytest.mark.parametrize("words", [["a"], "text", [1, 2], None])
def test_unusable_words_are_ignored_not_fatal(words):
    payload = _timed_payload(words)

    result = _provider(_respond_with(payload)).transcribe(AUDIO)

    assert result.timed_text == ()
    assert result.transcript == payload["transcript"]


def test_blank_words_are_skipped():
    result = _provider(_respond_with(_timed_payload(["a", "  "]))).transcribe(AUDIO)

    assert [item.text for item in result.timed_text] == ["a"]