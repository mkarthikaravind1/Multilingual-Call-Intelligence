from collections.abc import Callable
from app.ai.llm.client import LLMClient
from app.ai.llm.groq_client import GroqLLMClient
from app.ai.question.llm_provider import LLMQuestionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.core.config import Settings, get_settings
from app.ai.asr.provider import ASRProvider
from app.ai.asr.sarvam_provider import SarvamASRProvider
from app.ai.language.provider import LanguageIdentificationProvider
from app.ai.language.sarvam_provider import SarvamLanguageProvider

class UnsupportedProviderError(ValueError):
    pass


def _build_groq(model: str | None) -> LLMClient:
    return GroqLLMClient(model=model)


_LLM_CLIENT_BUILDERS: dict[str, Callable[[str | None], LLMClient]] = {
    "groq": _build_groq,
}


def create_llm_client(
    settings: Settings | None = None, model: str | None = None
) -> LLMClient:
    settings = settings or get_settings()
    name = settings.llm_provider.strip().lower()
    builder = _LLM_CLIENT_BUILDERS.get(name)
    if builder is None:
        raise UnsupportedProviderError(
            f"Unsupported LLM provider: {settings.llm_provider!r}. "
            f"Available: {sorted(_LLM_CLIENT_BUILDERS)}."
        )
    return builder(model)


def create_question_provider(
    llm_client: LLMClient | None = None, settings: Settings | None = None
) -> QuestionSuggestionProvider:
    if llm_client is None:
        llm_client = create_llm_client(settings)
    return LLMQuestionProvider(llm_client)

def _build_sarvam_asr(settings: Settings) -> ASRProvider:
    return SarvamASRProvider(settings)


_ASR_PROVIDER_BUILDERS: dict[str, Callable[[Settings], ASRProvider]] = {
    "sarvam": _build_sarvam_asr,
}


def create_asr_provider(settings: Settings | None = None) -> ASRProvider:
    settings = settings or get_settings()
    name = settings.asr_provider.strip().lower()
    builder = _ASR_PROVIDER_BUILDERS.get(name)
    if builder is None:
        raise UnsupportedProviderError(
            f"Unsupported ASR provider: {settings.asr_provider!r}. "
            f"Available: {sorted(_ASR_PROVIDER_BUILDERS)}."
        )
    return builder(settings)

def _build_sarvam_language(settings: Settings) -> LanguageIdentificationProvider:
    return SarvamLanguageProvider(settings)


_LANGUAGE_PROVIDER_BUILDERS: dict[
    str, Callable[[Settings], LanguageIdentificationProvider]
] = {
    "sarvam": _build_sarvam_language,
}


def create_language_provider(
    settings: Settings | None = None,
) -> LanguageIdentificationProvider:
    settings = settings or get_settings()
    name = settings.language_provider.strip().lower()
    builder = _LANGUAGE_PROVIDER_BUILDERS.get(name)
    if builder is None:
        raise UnsupportedProviderError(
            f"Unsupported language provider: {settings.language_provider!r}. "
            f"Available: {sorted(_LANGUAGE_PROVIDER_BUILDERS)}."
        )
    return builder(settings)