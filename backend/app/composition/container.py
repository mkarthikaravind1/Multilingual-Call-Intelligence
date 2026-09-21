from collections.abc import Sequence
from dataclasses import dataclass

from app.ai.speaker.provider import DiarizedSegment
from app.composition.services import (
    build_audio_processing_pipeline,
    build_call_service,
    build_call_workflow_service,
)
from app.core.config import Settings, get_settings
from app.services.audio_processing_pipeline import AudioProcessingPipeline
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService


@dataclass(frozen=True)
class ApplicationServices:
    call_service: CallService
    workflow_service: CallWorkflowService
    audio_pipeline: AudioProcessingPipeline


def build_application_services(
    settings: Settings | None = None,
    diarization_segments: Sequence[DiarizedSegment] = (),
) -> ApplicationServices:
    settings = settings or get_settings()
    call_service = build_call_service()
    workflow_service = build_call_workflow_service(
        settings=settings, call_service=call_service
    )
    audio_pipeline = build_audio_processing_pipeline(
        workflow_service, diarization_segments, settings=settings
    )
    return ApplicationServices(
        call_service=call_service,
        workflow_service=workflow_service,
        audio_pipeline=audio_pipeline,
    )