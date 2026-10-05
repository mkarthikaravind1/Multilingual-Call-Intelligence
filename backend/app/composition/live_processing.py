import logging
from collections.abc import Sequence

from app.ai.llm.client import LLMClient

from app.ai.asr.provider import ASRProvider
from app.ai.language.provider import LanguageIdentificationProvider
from app.ai.speaker.provider import DiarizedSegment
from app.composition.providers import create_llm_client
from app.composition.services import build_audio_processing_pipeline
from app.composition.speaker_sessions import (
    build_session_role_provider,
    build_speaker_session_registry,
)
from app.core.config import Settings
from app.services.audio_processing_pipeline import (
    AudioProcessingPipeline,
    UtteranceProcessor,
)
from app.services.live_chunk_processing_service import LiveChunkProcessingService
from app.services.speaker_session_registry import SpeakerSessionRegistry

logger = logging.getLogger(__name__)


def build_live_chunk_processing_service(
    workflow_service: UtteranceProcessor,
    diarization_segments: Sequence[DiarizedSegment],
    settings: Settings | None = None,
    asr_provider: ASRProvider | None = None,
    language_provider: LanguageIdentificationProvider | None = None,
    registry: SpeakerSessionRegistry | None = None,
) -> LiveChunkProcessingService:
    registry = registry or build_speaker_session_registry()
    llm_client = _role_llm_client(settings)

    def pipeline_for_call(call_id: str) -> AudioProcessingPipeline:
        return build_audio_processing_pipeline(
            workflow_service,
            diarization_segments,
            settings=settings,
            asr_provider=asr_provider,
            language_provider=language_provider,
            role_provider=build_session_role_provider(
                registry.get_or_create(call_id),
                settings=settings,
                evidence_store=registry.evidence_store(call_id),
                llm_client=llm_client,
            ),
        )

    return LiveChunkProcessingService(pipeline_for_call)

def _role_llm_client(settings: Settings | None) -> LLMClient | None:
    if settings is None or not settings.role_llm_enabled:
        return None
    try:
        # The judge runs inside live chunk processing: on a rate limit it
        # gives up (and asks again a few lines later) instead of holding up
        # the call's transcription while the provider asks it to wait.
        return create_llm_client(settings, max_retries=0)
    except Exception as exc:
        logger.warning("Speaker roles will not use the LLM: %s", exc)
        return None
