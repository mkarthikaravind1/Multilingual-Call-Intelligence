from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole as AISpeakerRole,
    SpeakerRoleAssignment,
)
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_workflow_service import CallAnalysisResult
from collections.abc import Callable
from uuid import uuid4
from typing import Protocol

_AI_TO_DOMAIN_ROLE: dict[AISpeakerRole, SpeakerRole] = {
    AISpeakerRole.ICR: SpeakerRole.ICR,
    AISpeakerRole.CUSTOMER: SpeakerRole.CUSTOMER,
}


class AudioPipelineError(Exception):
    pass

class UtteranceProcessor(Protocol):
    def process_utterance(
        self, call_id: str, utterance: Utterance
    ) -> CallAnalysisResult: ...

class AudioProcessingPipeline:
    def __init__(
        self,
        asr_provider: ASRProvider,
        language_provider: LanguageIdentificationProvider,
        diarization_provider: DiarizationProvider,
        role_provider: RoleIdentificationProvider,
        workflow_service: UtteranceProcessor,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._asr_provider = asr_provider
        self._language_provider = language_provider
        self._diarization_provider = diarization_provider
        self._role_provider = role_provider
        self._workflow_service = workflow_service
        self._id_factory = id_factory

    def process_audio(
        self, call_id: str, audio: bytes, start_offset: float = 0.0
    ) -> CallAnalysisResult:
        utterance = self.build_utterance(audio, start_offset)
        return self._workflow_service.process_utterance(call_id, utterance)

    def build_utterance(self, audio: bytes, start_offset: float = 0.0) -> Utterance:
        if not audio:
            raise AudioPipelineError("audio must not be empty.")
        if start_offset < 0:
            raise AudioPipelineError("start_offset must not be negative.")

        asr_result = self._transcribe(audio)
        languages = self._identify_languages(asr_result)
        role = self._resolve_role(audio, asr_result)

        try:
            return Utterance(
                utterance_id=self._id_factory(),
                transcript=asr_result.transcript,
                speaker_role=role,
                languages=languages,
                start_time=asr_result.start_time + start_offset,
                end_time=asr_result.end_time + start_offset,
                confidence=asr_result.confidence,
            )
        except ValueError as exc:
            raise AudioPipelineError(
                f"Provider results do not form a valid utterance: {exc}"
            ) from exc

    def _transcribe(self, audio: bytes) -> ASRResult:
        result = self._asr_provider.transcribe(audio)
        if not isinstance(result, ASRResult):
            raise AudioPipelineError("ASR provider returned an invalid result.")
        if not isinstance(result.transcript, str) or not result.transcript.strip():
            raise AudioPipelineError("ASR provider returned an empty transcript.")
        if result.end_time < result.start_time:
            raise AudioPipelineError("ASR provider returned end_time before start_time.")
        return result

    def _identify_languages(self, asr_result: ASRResult) -> tuple[str, ...]:
        result = self._language_provider.identify(asr_result.transcript)
        if not isinstance(result, LanguageIdentificationResult):
            raise AudioPipelineError("Language provider returned an invalid result.")

        codes: list[str] = []
        for span in result.languages:
            if not isinstance(span, LanguageSpan):
                raise AudioPipelineError("Language provider returned an invalid span.")
            if span.language not in codes:
                codes.append(span.language)

        return tuple(codes) if codes else (asr_result.detected_language,)

    def _resolve_role(self, audio: bytes, asr_result: ASRResult) -> SpeakerRole:
        segments = self._diarization_provider.diarize(audio)
        if (
            not isinstance(segments, list)
            or not segments
            or not all(isinstance(s, DiarizedSegment) for s in segments)
        ):
            raise AudioPipelineError("Diarization provider returned no valid segments.")

        assignments = self._role_provider.identify_roles(segments)
        if not isinstance(assignments, list) or not all(
            isinstance(a, SpeakerRoleAssignment) for a in assignments
        ):
            raise AudioPipelineError("Role provider returned invalid assignments.")

        speaker_id = self._dominant_speaker(segments, asr_result)
        roles = {a.speaker_id: a.role for a in assignments}
        ai_role = roles.get(speaker_id)
        role = _AI_TO_DOMAIN_ROLE.get(ai_role) if ai_role is not None else None
        if role is None:
            raise AudioPipelineError(
                f"No usable role was assigned to speaker {speaker_id!r}."
            )
        return role

    @staticmethod
    def _dominant_speaker(
        segments: list[DiarizedSegment], asr_result: ASRResult
    ) -> str:
        overlaps: dict[str, float] = {}
        for segment in segments:
            overlap = min(segment.end_time, asr_result.end_time) - max(
                segment.start_time, asr_result.start_time
            )
            if overlap > 0:
                overlaps[segment.speaker_id] = (
                    overlaps.get(segment.speaker_id, 0.0) + overlap
                )
        if not overlaps:
            raise AudioPipelineError(
                "No diarized segment overlaps the transcribed speech."
            )
        return max(overlaps, key=lambda speaker_id: overlaps[speaker_id])