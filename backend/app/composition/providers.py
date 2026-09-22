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

from collections.abc import Callable, Mapping, Sequence
from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.ai.speaker.order_based_role_provider import (
    DEFAULT_ROLE_ORDER,
    OrderBasedRoleIdentificationProvider,
)
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole,
)
from app.ai.speaker.scripted_diarization_provider import ScriptedDiarizationProvider
from app.ai.speaker.static_role_provider import StaticRoleIdentificationProvider
from app.ai.speaker.pyannote_provider import PyannoteDiarizationProvider
from app.ai.summary.llm_provider import LLMPostCallSummaryProvider
from app.ai.summary.provider import SummaryGenerationProvider
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider

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



def create_complaint_provider(
    llm_client: LLMClient | None = None, settings: Settings | None = None
) -> ComplaintDetectionProvider:
    if llm_client is None:
        llm_client = create_llm_client(settings)
    return LLMComplaintProvider(llm_client)


def create_sentiment_provider(
    llm_client: LLMClient | None = None, settings: Settings | None = None
) -> SentimentAnalysisProvider:
    if llm_client is None:
        llm_client = create_llm_client(settings)
    return LLMSentimentProvider(llm_client)

def _build_rule_based_summary(
    llm_client: LLMClient | None, settings: Settings
) -> SummaryGenerationProvider:
    return RuleBasedSummaryProvider()


def _build_llm_summary(
    llm_client: LLMClient | None, settings: Settings
) -> SummaryGenerationProvider:
    if llm_client is None:
        llm_client = create_llm_client(settings)
    return LLMPostCallSummaryProvider(llm_client)


_SUMMARY_PROVIDER_BUILDERS: dict[
    str, Callable[[LLMClient | None, Settings], SummaryGenerationProvider]
] = {
    "rule_based": _build_rule_based_summary,
    "llm": _build_llm_summary,
}


def create_summary_provider(
    llm_client: LLMClient | None = None, settings: Settings | None = None
) -> SummaryGenerationProvider:
    settings = settings or get_settings()
    name = settings.summary_provider.strip().lower()
    builder = _SUMMARY_PROVIDER_BUILDERS.get(name)
    if builder is None:
        raise UnsupportedProviderError(
            f"Unsupported summary provider: {settings.summary_provider!r}. "
            f"Available: {sorted(_SUMMARY_PROVIDER_BUILDERS)}."
        )
    return builder(llm_client, settings)

def _build_scripted_diarization(
    segments: Sequence[DiarizedSegment], settings: Settings
) -> DiarizationProvider:
    return ScriptedDiarizationProvider(segments)


def _build_pyannote_diarization(
    segments: Sequence[DiarizedSegment], settings: Settings
) -> DiarizationProvider:
    return PyannoteDiarizationProvider(
        model=settings.pyannote_model,
        token=settings.huggingface_token or None,
    )


_DIARIZATION_PROVIDER_BUILDERS: dict[
    str, Callable[[Sequence[DiarizedSegment], Settings], DiarizationProvider]
] = {
    "scripted": _build_scripted_diarization,
    "pyannote": _build_pyannote_diarization,
}

def create_diarization_provider(
    segments: Sequence[DiarizedSegment], settings: Settings | None = None
) -> DiarizationProvider:
    settings = settings or get_settings()
    name = settings.diarization_provider.strip().lower()
    builder = _DIARIZATION_PROVIDER_BUILDERS.get(name)
    if builder is None:
        raise UnsupportedProviderError(
            f"Unsupported diarization provider: {settings.diarization_provider!r}. "
            f"Available: {sorted(_DIARIZATION_PROVIDER_BUILDERS)}."
        )
    return builder(segments,settings)


def _build_order_based_roles(
    role_by_speaker: Mapping[str, SpeakerRole] | None,
    role_order: Sequence[SpeakerRole],
) -> RoleIdentificationProvider:
    return OrderBasedRoleIdentificationProvider(role_order)


def _build_static_roles(
    role_by_speaker: Mapping[str, SpeakerRole] | None,
    role_order: Sequence[SpeakerRole],
) -> RoleIdentificationProvider:
    if role_by_speaker is None:
        raise ValueError("role_by_speaker is required for the static role provider.")
    return StaticRoleIdentificationProvider(role_by_speaker)


_ROLE_PROVIDER_BUILDERS: dict[
    str,
    Callable[
        [Mapping[str, SpeakerRole] | None, Sequence[SpeakerRole]],
        RoleIdentificationProvider,
    ],
] = {
    "order_based": _build_order_based_roles,
    "static": _build_static_roles,
}


def create_role_provider(
    settings: Settings | None = None,
    *,
    role_by_speaker: Mapping[str, SpeakerRole] | None = None,
    role_order: Sequence[SpeakerRole] = DEFAULT_ROLE_ORDER,
) -> RoleIdentificationProvider:
    settings = settings or get_settings()
    name = settings.role_provider.strip().lower()
    builder = _ROLE_PROVIDER_BUILDERS.get(name)
    if builder is None:
        raise UnsupportedProviderError(
            f"Unsupported role provider: {settings.role_provider!r}. "
            f"Available: {sorted(_ROLE_PROVIDER_BUILDERS)}."
        )
    return builder(role_by_speaker, role_order)