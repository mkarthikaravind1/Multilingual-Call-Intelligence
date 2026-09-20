import json

import httpx
import pytest

from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.language.sarvam_provider import (
    SarvamLanguageConfigurationError,
    SarvamLanguageError,
    SarvamLanguageProvider,
    SarvamLanguageRequestError,
    SarvamLanguageResponseError,
)
from app.core.config import Settings
from app.composition import providers

API_KEY = "test-key"
TEXT = "vanakkam sir"


def _settings(**overrides) -> Settings:
    values = {
        "sarvam_api_key": API_KEY,
        "sarvam_base_url": "https://sarvam.test",
        "sarvam_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def _payload(**overrides) -> dict:
    payload = {"request_id": "req-1", "language_code": "ta-IN", "script_code": "Taml"}
    payload.update(overrides)
    return payload


def _respond_with(body, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


def _provider(handler, **settings_overrides) -> SarvamLanguageProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SarvamLanguageProvider(_settings(**settings_overrides), client=client)


def _capture(captured: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_payload())

    return handler


def test_provider_satisfies_language_provider_contract():
    provider = _provider(_respond_with(_payload()))

    assert isinstance(provider, LanguageIdentificationProvider)
    assert isinstance(provider.identify(TEXT), LanguageIdentificationResult)


def test_successful_detection_returns_single_supported_language():
    result = _provider(_respond_with(_payload())).identify(TEXT)

    assert result.languages == [LanguageSpan(language="ta", confidence=None)]
    assert result.is_mixed is False


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

    assert provider.identify(TEXT).languages[0].language == expected


def test_sarvam_reports_one_language_so_result_is_never_mixed():
    result = _provider(_respond_with(_payload(language_code="en-IN"))).identify(
        "vanakkam sir, my car service is pending"
    )

    assert len(result.languages) == 1
    assert result.is_mixed is False


def test_request_is_built_from_settings():
    captured: list[httpx.Request] = []

    _provider(_capture(captured)).identify(TEXT)

    request = captured[0]
    assert request.method == "POST"
    assert str(request.url) == "https://sarvam.test/text-lid"
    assert request.headers["api-subscription-key"] == API_KEY
    assert json.loads(request.content) == {"input": TEXT}


def test_trailing_slash_in_base_url_is_normalised():
    captured: list[httpx.Request] = []

    _provider(_capture(captured), sarvam_base_url="https://sarvam.test/").identify(TEXT)

    assert str(captured[0].url) == "https://sarvam.test/text-lid"


def test_text_longer_than_api_limit_is_truncated():
    captured: list[httpx.Request] = []

    _provider(_capture(captured)).identify("a" * 1500)

    assert len(json.loads(captured[0].content)["input"]) == 1000


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_is_rejected_without_calling_sarvam(text):
    captured: list[httpx.Request] = []

    with pytest.raises(SarvamLanguageError):
        _provider(_capture(captured)).identify(text)

    assert captured == []


MALFORMED_PAYLOADS = {
    "not_an_object": ["ta-IN"],
    "missing_language": {"request_id": "req-1", "script_code": "Taml"},
    "null_language": _payload(language_code=None),
    "non_string_language": _payload(language_code=123),
    "blank_language": _payload(language_code=" "),
}


@pytest.mark.parametrize(
    "body", MALFORMED_PAYLOADS.values(), ids=MALFORMED_PAYLOADS.keys()
)
def test_malformed_responses_raise_response_error(body):
    with pytest.raises(SarvamLanguageResponseError):
        _provider(_respond_with(body)).identify(TEXT)


@pytest.mark.parametrize("content", [b"<html>oops</html>", b""])
def test_non_json_response_raises_response_error(content):
    def handler(request):
        return httpx.Response(200, content=content)

    with pytest.raises(SarvamLanguageResponseError):
        _provider(handler).identify(TEXT)


@pytest.mark.parametrize("code", ["hi-IN", "bn-IN", "xx-IN", "fr"])
def test_unsupported_languages_raise_response_error(code):
    provider = _provider(_respond_with(_payload(language_code=code)))

    with pytest.raises(SarvamLanguageResponseError, match="unsupported"):
        provider.identify(TEXT)


@pytest.mark.parametrize("status", [400, 403, 422, 429, 500, 503])
def test_http_errors_raise_request_error_without_leaking_details(status):
    body = {"error": {"message": "internal-detail", "code": "x", "request_id": "r"}}

    with pytest.raises(SarvamLanguageRequestError) as exc_info:
        _provider(_respond_with(body, status)).identify(TEXT)

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
def test_network_errors_raise_request_error(error):
    def handler(request):
        raise error

    with pytest.raises(SarvamLanguageRequestError) as exc_info:
        _provider(handler).identify(TEXT)

    assert "boom" not in str(exc_info.value)
    assert exc_info.value.__cause__ is error


@pytest.mark.parametrize("key", ["not_configured", "", "   "])
def test_missing_api_key_is_rejected(key):
    with pytest.raises(SarvamLanguageConfigurationError, match="API key"):
        SarvamLanguageProvider(_settings(sarvam_api_key=key))


def test_missing_base_url_is_rejected():
    with pytest.raises(SarvamLanguageConfigurationError, match="base URL"):
        SarvamLanguageProvider(_settings(sarvam_base_url=""))


@pytest.mark.parametrize(
    "error_type",
    [
        SarvamLanguageConfigurationError,
        SarvamLanguageRequestError,
        SarvamLanguageResponseError,
    ],
)
def test_specific_errors_share_a_common_base(error_type):
    assert issubclass(error_type, SarvamLanguageError)

from app.ai.language.provider import LanguageIdentificationProvider
from app.ai.language.sarvam_provider import (
    SarvamLanguageConfigurationError,
    SarvamLanguageProvider,
)
from app.composition.providers import UnsupportedProviderError, create_language_provider


class FakeSarvamLanguageProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


def test_create_language_provider_builds_sarvam_from_settings(monkeypatch):
    monkeypatch.setattr(providers, "SarvamLanguageProvider", FakeSarvamLanguageProvider)
    settings = Settings.model_construct(language_provider="SARVAM")

    provider = create_language_provider(settings)

    assert isinstance(provider, FakeSarvamLanguageProvider)
    assert provider.settings is settings


@pytest.mark.parametrize("name", ["not_configured", "unknown"])
def test_create_language_provider_rejects_unsupported_provider(name):
    with pytest.raises(UnsupportedProviderError, match=name):
        create_language_provider(Settings.model_construct(language_provider=name))


def test_create_language_provider_returns_real_sarvam_provider_without_network():
    settings = Settings.model_construct(
        language_provider="sarvam", sarvam_api_key="test-key"
    )

    provider = create_language_provider(settings)

    assert isinstance(provider, SarvamLanguageProvider)
    assert isinstance(provider, LanguageIdentificationProvider)


def test_create_language_provider_fails_fast_when_api_key_missing():
    settings = Settings.model_construct(language_provider="sarvam")

    with pytest.raises(SarvamLanguageConfigurationError, match="API key"):
        create_language_provider(settings)