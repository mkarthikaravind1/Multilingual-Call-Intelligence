from collections.abc import Sequence

from app.ai.asr.provider import ASRProvider
from app.ai.language.provider import LanguageIdentificationProvider
from app.ai.speaker.provider import DiarizedSegment
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


def build_live_chunk_processing_service(
    workflow_service: UtteranceProcessor,
    diarization_segments: Sequence[DiarizedSegment],
    settings: Settings | None = None,
    asr_provider: ASRProvider | None = None,
    language_provider: LanguageIdentificationProvider | None = None,
    registry: SpeakerSessionRegistry | None = None,
) -> LiveChunkProcessingService:
    registry = registry or build_speaker_session_registry()

    def pipeline_for_call(call_id: str) -> AudioProcessingPipeline:
        return build_audio_processing_pipeline(
            workflow_service,
            diarization_segments,
            settings=settings,
            asr_provider=asr_provider,
            language_provider=language_provider,
            role_provider=build_session_role_provider(
                registry.get_or_create(call_id)
            ),
        )

    return LiveChunkProcessingService(pipeline_for_call)