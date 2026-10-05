"""Speaker roles for one live call, kept in the call's SpeakerSession.

Two ways a speaker gets a role:

* Separate tracks: a call whose two sides are streamed separately tells
  each track's role outright (observe_speech with role=...), and the track
  is recorded as a speaker of the session.
* Mixed audio: the diarizer's per-chunk labels are mapped to call-wide
  speakers by voice (VoiceTracker). Each speaker's speech is scored for
  evidence of being the ICR or the customer (ContentRoleScorer); once the
  evidence is clear, or the optional LLM judge decides, the speaker gets a
  role and the other speaker the opposite one.

A role, once given, is locked for the rest of the call (SpeakerSession
refuses a remap). Until then speech stays UNKNOWN; nothing is guessed from
who spoke first.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.ai.speaker.content_role_scorer import ContentRoleScorer
from app.ai.speaker.llm_role_judge import LLMRoleJudge
from app.ai.speaker.provider import (
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole as AISpeakerRole,
    SpeakerRoleAssignment,
)
from app.ai.speaker.voice_tracker import VoiceTracker
from app.domain.speaker_session import SpeakerRoleConflictError, SpeakerSession
from app.domain.utterance import SpeakerRole
from app.observability.metrics import SPEAKER_ROLES_DECIDED

logger = logging.getLogger(__name__)

_AI_TO_DOMAIN: dict[AISpeakerRole, SpeakerRole] = {
    AISpeakerRole.ICR: SpeakerRole.ICR,
    AISpeakerRole.CUSTOMER: SpeakerRole.CUSTOMER,
    AISpeakerRole.UNKNOWN: SpeakerRole.UNKNOWN,
}
_DOMAIN_TO_AI: dict[SpeakerRole, AISpeakerRole] = {
    domain: ai for ai, domain in _AI_TO_DOMAIN.items()
}
_OPPOSITE = {SpeakerRole.ICR: SpeakerRole.CUSTOMER, SpeakerRole.CUSTOMER: SpeakerRole.ICR}

# Content evidence needed to give a speaker a role: a total score this far
# from zero, and this much clearer than the other speaker's.
DECISIVE_SCORE = 3
DECISIVE_MARGIN = 2
# The LLM judge is asked once at least this many lines have been heard
# with both speakers, then again every few lines, at most a few times.
LLM_MIN_LINES = 3
LLM_EVERY_LINES = 3
LLM_MAX_ATTEMPTS = 3
_MAX_KEPT_LINES = 12


class SpeakerEvidenceStore:
    """Where a call's voice profiles and role evidence are kept between
    chunks (see SpeakerSessionRegistry); the default keeps them here."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def load(self) -> Mapping[str, Any]:
        return self._data

    def save(self, data: Mapping[str, Any]) -> None:
        self._data = dict(data)


class SessionRoleIdentificationProvider(RoleIdentificationProvider):
    def __init__(
        self,
        session: SpeakerSession,
        role_order: Sequence[AISpeakerRole] | None = None,  # unused; kept for callers
        *,
        voice_tracker: VoiceTracker | None = None,
        scorer: ContentRoleScorer | None = None,
        llm_judge: LLMRoleJudge | None = None,
        evidence_store: SpeakerEvidenceStore | None = None,
    ) -> None:
        self._session = session
        self._tracker = voice_tracker or VoiceTracker()
        self._scorer = scorer or ContentRoleScorer()
        self._llm_judge = llm_judge
        self._store = evidence_store or SpeakerEvidenceStore()
        # The latest chunk's labels -> call-wide speaker ids.
        self._chunk_speakers: dict[str, str] = {}

    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        state = self._load()
        self._chunk_speakers = self._tracker.match(segments)
        if self._chunk_speakers:
            state["voices"] = self._tracker.to_dict()
            self._save(state)
            self._complete_roles()

        first_start: dict[str, float] = {}
        for segment in segments:
            current = first_start.get(segment.speaker_id)
            if current is None or segment.start_time < current:
                first_start[segment.speaker_id] = segment.start_time

        assignments: list[SpeakerRoleAssignment] = []
        for label in sorted(first_start, key=first_start.__getitem__):
            speaker_id = self._chunk_speakers.get(label, label)
            mapped_role = self._session.role_for(speaker_id)
            assignments.append(
                SpeakerRoleAssignment(
                    speaker_id=label,
                    role=(
                        _DOMAIN_TO_AI[mapped_role]
                        if mapped_role is not None
                        else AISpeakerRole.UNKNOWN
                    ),
                )
            )
        return assignments

    def observe_speech(
        self, speaker_id: str, transcript: str, *, role: AISpeakerRole | None = None
    ) -> AISpeakerRole | None:
        if role is not None and role != AISpeakerRole.UNKNOWN:
            self._assign(speaker_id, _AI_TO_DOMAIN[role], method="track")
            return role

        speaker = self._chunk_speakers.get(speaker_id)
        if speaker is None:
            # Not recognised by voice: no call-wide speaker to learn about.
            return None
        known = self._session.role_for(speaker)
        if known is not None:
            return _DOMAIN_TO_AI[known]

        state = self._load()
        scores: dict[str, int] = state.setdefault("scores", {})
        scores[speaker] = scores.get(speaker, 0) + self._scorer.score(transcript)
        lines: list[list[str]] = state.setdefault("lines", [])
        lines.append([speaker, transcript])
        del lines[:-_MAX_KEPT_LINES]
        self._save(state)

        decided = self._decide_from_scores(scores) or self._ask_llm(state)
        if decided is not None:
            icr_speaker, how = decided
            logger.info(
                "Call %r: %s is the ICR (%s)", self._session.call_id, icr_speaker, how
            )
            self._assign(
                icr_speaker, SpeakerRole.ICR, method="llm" if how == "LLM judgement" else "content"
            )
            self._complete_roles()

        known = self._session.role_for(speaker)
        return _DOMAIN_TO_AI[known] if known is not None else None

    def _decide_from_scores(self, scores: Mapping[str, int]) -> tuple[str, str] | None:
        speakers = list(self._tracker.speaker_ids) or list(scores)
        for speaker in speakers:
            score = scores.get(speaker, 0)
            others = [scores.get(s, 0) for s in speakers if s != speaker]
            other_best = max(others, default=0)
            other_worst = min(others, default=0)
            if score >= DECISIVE_SCORE and score - other_best >= DECISIVE_MARGIN:
                return speaker, f"what they said scores {score:+d}"
            if score <= -DECISIVE_SCORE and other_worst - score >= DECISIVE_MARGIN:
                # This speaker is the customer: the ICR is the other one, if
                # there is one yet.
                icr = [s for s in speakers if s != speaker]
                if len(icr) == 1:
                    return icr[0], f"the other speaker's speech scores {score:+d}"
                self._assign(speaker, SpeakerRole.CUSTOMER, method="content")
        return None

    def _ask_llm(self, state: dict[str, Any]) -> tuple[str, str] | None:
        if self._llm_judge is None:
            return None
        lines = [(speaker, text) for speaker, text in state.get("lines", [])]
        attempts = state.get("llm_attempts", 0)
        heard = state.get("lines_heard", 0) + 1
        state["lines_heard"] = heard
        self._save(state)
        if (
            attempts >= LLM_MAX_ATTEMPTS
            or len({speaker for speaker, _ in lines}) < 2
            or heard < LLM_MIN_LINES
            or (heard - LLM_MIN_LINES) % LLM_EVERY_LINES
        ):
            return None
        state["llm_attempts"] = attempts + 1
        self._save(state)
        icr = self._llm_judge.icr_speaker(lines)
        return (icr, "LLM judgement") if icr is not None else None

    def _complete_roles(self) -> None:
        """A two-party call: once one speaker's role is known, the other
        speaker has the opposite one."""
        speakers = self._tracker.speaker_ids
        if len(speakers) != 2:
            return
        roles = [self._session.role_for(s) for s in speakers]
        for index, speaker in enumerate(speakers):
            other = roles[1 - index]
            if roles[index] is None and other in _OPPOSITE:
                self._assign(speaker, _OPPOSITE[other], method="other_speaker")

    def _assign(self, speaker_id: str, role: SpeakerRole, *, method: str) -> None:
        if role == SpeakerRole.UNKNOWN:
            return
        if self._session.role_for(speaker_id) == role:
            return
        try:
            self._session.assign(speaker_id, role)
            SPEAKER_ROLES_DECIDED.inc(method)
        except SpeakerRoleConflictError:
            logger.warning(
                "Call %r: keeping %s's role; it was already decided.",
                self._session.call_id,
                speaker_id,
            )

    def _load(self) -> dict[str, Any]:
        state = dict(self._store.load() or {})
        if not self._tracker.speaker_ids and state.get("voices"):
            # Another instance served this call's stream before.
            self._tracker.load(state["voices"])
        return state

    def _save(self, state: Mapping[str, Any]) -> None:
        try:
            self._store.save(state)
        except Exception:
            logger.exception("Could not keep the speaker evidence of call %r", self._session.call_id)

