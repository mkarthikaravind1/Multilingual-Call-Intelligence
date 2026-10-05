from collections.abc import Sequence

from app.ai.llm.client import LLMClient
from app.ai.speaker.content_role_scorer import ContentRoleScorer
from app.ai.speaker.llm_role_judge import LLMRoleJudge
from app.ai.speaker.provider import SpeakerRole
from app.ai.speaker.session_role_provider import (
    SessionRoleIdentificationProvider,
    SpeakerEvidenceStore,
)
from app.ai.speaker.voice_tracker import VoiceTracker
from app.core.config import Settings
from app.domain.speaker_session import SpeakerSession
from app.services.live_state_store import LiveStateStore
from app.services.speaker_session_registry import SpeakerSessionRegistry


def build_speaker_session_registry(store: LiveStateStore | None = None) -> SpeakerSessionRegistry:
    """Pass the shared live-state store when several instances serve calls."""
    return SpeakerSessionRegistry(store)


def build_session_role_provider(
    session: SpeakerSession,
    role_order: Sequence[SpeakerRole] | None = None,
    *,
    settings: Settings | None = None,
    evidence_store: SpeakerEvidenceStore | None = None,
    llm_client: LLMClient | None = None,
) -> SessionRoleIdentificationProvider:
    settings = settings or Settings()
    return SessionRoleIdentificationProvider(
        session,
        role_order,
        voice_tracker=VoiceTracker(
            match_threshold=settings.speaker_match_threshold,
            max_speakers=settings.speaker_max_per_call,
        ),
        scorer=ContentRoleScorer(settings.role_icr_phrases.split(",")),
        llm_judge=LLMRoleJudge(llm_client) if llm_client is not None else None,
        evidence_store=evidence_store,
    )
