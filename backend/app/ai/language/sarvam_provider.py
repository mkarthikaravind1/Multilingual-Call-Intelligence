from typing import Any

import httpx

from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.core.config import Settings, get_settings
from app.core.constants import SUPPORTED_LANGUAGES

_ENDPOINT_PATH = "/text-lid"
_MAX_INPUT_CHARS = 1000
_UNCONFIGURED = "not_configured"


class SarvamLanguageError(Exception):
    pass


class SarvamLanguageConfigurationError(SarvamLanguageError):
    pass


class SarvamLanguageRequestError(SarvamLanguageError):
    pass


class SarvamLanguageResponseError(SarvamLanguageError):
    pass


class SarvamLanguageProvider(LanguageIdentificationProvider):
    def __init__(
        self, settings: Settings | None = None, client: httpx.Client | None = None
    ) -> None:
        settings = settings or get_settings()
        api_key = settings.sarvam_api_key.strip()
        base_url = settings.sarvam_base_url.strip().rstrip("/")

        if not api_key or api_key == _UNCONFIGURED:
            raise SarvamLanguageConfigurationError("Sarvam API key is not configured.")
        if not base_url:
            raise SarvamLanguageConfigurationError(
                "Sarvam base URL must be configured."
            )

        self._api_key = api_key
        self._url = f"{base_url}{_ENDPOINT_PATH}"
        self._client = client or httpx.Client(timeout=settings.sarvam_timeout_seconds)

    def identify(self, text: str) -> LanguageIdentificationResult:
        if not text or not text.strip():
            raise SarvamLanguageError("text must not be empty.")
        return self._to_result(self._post(text[:_MAX_INPUT_CHARS]))

    def _post(self, text: str) -> Any:
        try:
            response = self._client.post(
                self._url,
                headers={"api-subscription-key": self._api_key},
                json={"input": text},
            )
        except httpx.HTTPError as exc:
            raise SarvamLanguageRequestError(
                f"Sarvam request failed ({type(exc).__name__})."
            ) from exc

        if response.status_code != 200:
            raise SarvamLanguageRequestError(
                f"Sarvam returned HTTP {response.status_code}."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise SarvamLanguageResponseError(
                "Sarvam returned a non-JSON response."
            ) from exc

    @staticmethod
    def _to_result(payload: Any) -> LanguageIdentificationResult:
        if not isinstance(payload, dict):
            raise SarvamLanguageResponseError("Sarvam response is not a JSON object.")

        code = payload.get("language_code")
        if not isinstance(code, str) or not code.strip():
            raise SarvamLanguageResponseError("Sarvam response has no language_code.")

        language = code.strip().split("-")[0].lower()
        if language not in SUPPORTED_LANGUAGES:
            raise SarvamLanguageResponseError(
                f"Sarvam returned unsupported language {code[:20]!r}."
            )

        return LanguageIdentificationResult(
            languages=[LanguageSpan(language=language, confidence=None)]
        )