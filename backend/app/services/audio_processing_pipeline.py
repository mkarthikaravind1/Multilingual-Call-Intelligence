import logging
import string
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Protocol
from uuid import uuid4

from app.ai.asr.provider import ASRProvider, ASRResult, NoSpeechDetected, TimedText
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.speaker.provider import (
    DiarizationError,
    DiarizationProvider,
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole as AISpeakerRole,
    SpeakerRoleAssignment,
)
from app.domain.conversation import UtteranceNotLatestError
from app.core.languages import INDIC_LANGUAGES
from app.domain.utterance import SpeakerRole, Utterance
from app.observability.metrics import PROVIDER_ERRORS, PROVIDER_REQUEST_DURATION
from app.services.call_workflow_service import CallAnalysisResult
from app.services.language_lock import LanguageLock
from app.services.speaker_alignment import align_timed_text_to_speakers

logger = logging.getLogger(__name__)

_AI_TO_DOMAIN_ROLE: dict[AISpeakerRole, SpeakerRole] = {
    AISpeakerRole.ICR: SpeakerRole.ICR,
    AISpeakerRole.CUSTOMER: SpeakerRole.CUSTOMER,
    AISpeakerRole.UNKNOWN: SpeakerRole.UNKNOWN,
}
_DOMAIN_TO_AI_ROLE: dict[SpeakerRole, AISpeakerRole] = {
    domain: ai for ai, domain in _AI_TO_DOMAIN_ROLE.items()
}


class AudioPipelineError(Exception):
    pass


class EmptyTranscriptError(AudioPipelineError, NoSpeechDetected):
    """The audio held no speech."""

class UtteranceProcessor(Protocol):
    def process_utterance(
        self, call_id: str, utterance: Utterance
    ) -> CallAnalysisResult: ...

    def process_utterance_update(
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
        language_lock: LanguageLock | None = None,
    ) -> None:
        self._asr_provider = asr_provider
        # Live audio: tells the ASR each speaker's language once it is
        # known (only for ASR providers that take a language hint).
        self._language_lock = (
            language_lock if getattr(asr_provider, "supports_language_hint", False) else None
        )
        self._language_provider = language_provider
        self._diarization_provider = diarization_provider
        self._role_provider = role_provider
        self._workflow_service = workflow_service
        self._id_factory = id_factory
        # Live audio: per track (None: a mixed stream), the utterance the
        # next chunk of that track may continue, if any.
        self._open_utterances: dict[str | None, Utterance] = {}
        # Live audio: where the latest utterance this pipeline added starts.
        self._latest_start: float | None = None

    def process_audio(
        self,
        call_id: str,
        audio: bytes,
        start_offset: float = 0.0,
        *,
        continues_previous: bool = False,
        ends_utterance: bool = True,
        track: str | None = None,
        speaker_role: SpeakerRole | None = None,
    ) -> CallAnalysisResult:
        """Transcribe one chunk of audio into the call.

        Live audio arrives in chunks cut at a time limit, so one sentence can
        span several chunks. A chunk whose speech continues the previous
        chunk's (continues_previous) extends the open utterance in place,
        keeping its utterance_id, so the transcript grows instead of
        splitting; ends_utterance (a pause, or the end of the stream) closes
        it. The defaults keep every chunk a separate utterance.

        A call whose two sides arrive as separate tracks passes each chunk's
        track and the speaker_role it belongs to: no diarization is needed
        then, and each track keeps its own open utterance.
        """
        # Taken up front: if this chunk fails, the next one starts afresh.
        open_utterance = self._open_utterances.pop(track, None)
        utterance = self._build_live_utterance(audio, start_offset, track, speaker_role)

        if continues_previous and open_utterance is not None and _can_continue(
            open_utterance, utterance
        ):
            extended = _continue_utterance(open_utterance, utterance)
            try:
                result = self._workflow_service.process_utterance_update(
                    call_id, extended
                )
            except UtteranceNotLatestError:
                # Another utterance was added in between; start a new one.
                logger.info(
                    "Utterance %r is no longer the latest of call %r; starting a new one.",
                    open_utterance.utterance_id,
                    call_id,
                )
            else:
                if not ends_utterance:
                    self._open_utterances[track] = extended
                return result

        utterance = self._in_call_order(utterance)
        result = self._workflow_service.process_utterance(call_id, utterance)
        self._latest_start = utterance.start_time
        if not ends_utterance:
            self._open_utterances[track] = utterance
        return result

    def _build_live_utterance(
        self,
        audio: bytes,
        start_offset: float,
        track: str | None,
        speaker_role: SpeakerRole | None,
    ) -> Utterance:
        self._validate_input(audio, start_offset)
        asr_result = self._transcribe_live(audio, track)
        if speaker_role is None:
            utterance = self._build_single_utterance(
                audio, asr_result, start_offset, learn_roles=True
            )
        else:
            languages = self._identify_languages(asr_result)
            if track is not None:
                # Keeps the call's speaker session in step with its tracks.
                self._observe_speech(track, asr_result.transcript, speaker_role)
            utterance = self._create_utterance(
                asr_result, speaker_role, languages, start_offset
            )
        if self._language_lock is not None:
            self._language_lock.observe(
                track, _heard_language(utterance.languages, asr_result.detected_language)
            )
        return utterance

    def _transcribe_live(self, audio: bytes, track: str | None) -> ASRResult:
        lock = self._language_lock
        hint = None if lock is None else lock.hint(track)
        try:
            return self._transcribe(audio, hint)
        except NoSpeechDetected:
            if lock is not None:
                lock.observe_no_speech(track)
            raise

    def _in_call_order(self, utterance: Utterance) -> Utterance:
        """The two tracks of a call are cut into chunks independently, so
        speech can be transcribed after speech that started later (e.g. a
        customer's long sentence and the ICR's short reply over it).
        Utterances are kept in the order they are added: such an utterance
        starts where the latest one does."""
        if self._latest_start is None or utterance.start_time >= self._latest_start:
            return utterance
        return replace(
            utterance,
            start_time=self._latest_start,
            end_time=max(utterance.end_time, self._latest_start),
        )

    def build_utterance(self, audio: bytes, start_offset: float = 0.0) -> Utterance:
        self._validate_input(audio, start_offset)
        asr_result = self._transcribe(audio)
        return self._build_single_utterance(
            audio, asr_result, start_offset, learn_roles=True
        )

    def build_utterances(
        self, audio: bytes, start_offset: float = 0.0
    ) -> list[Utterance]:
        self._validate_input(audio, start_offset)
        asr_result = self._transcribe(audio)
        if not asr_result.timed_text:
            return [self._build_single_utterance(audio, asr_result, start_offset)]

        if not all(isinstance(item, TimedText) for item in asr_result.timed_text):
            raise AudioPipelineError("ASR provider returned invalid timed text.")

        segments: list[DiarizedSegment] | None = None
        roles: dict[str, AISpeakerRole] | None = None
        try:
            segments, roles = self._diarize(audio)
            turns = align_timed_text_to_speakers(asr_result.timed_text, segments)
        except (AudioPipelineError, DiarizationError):
            logger.warning(
                "Diarization or speaker alignment failed; falling back to an unknown-role single utterance."
            )
            return [
                self._build_single_utterance(
                    audio,
                    asr_result,
                    start_offset,
                    diarization_segments=segments,
                    role_map=roles,
                )
            ]

        if not turns:
            logger.warning(
                "No diarized segments overlap the transcribed speech; falling back to an unknown-role utterance."
            )
            return [
                self._build_single_utterance(
                    audio,
                    asr_result,
                    start_offset,
                    diarization_segments=segments,
                    role_map=roles,
                )
            ]

        utterances: list[Utterance] = []
        for turn in turns:
            role = self._safe_domain_role(turn.speaker_id, roles)
            turn_result = replace(
                asr_result,
                transcript=turn.text,
                start_time=turn.start_time,
                end_time=turn.end_time,
            )
            languages = self._identify_languages(turn_result)
            utterances.append(
                self._create_utterance(turn_result, role, languages, start_offset)
            )
        return utterances

    @staticmethod
    def _validate_input(audio: bytes, start_offset: float) -> None:
        if not audio:
            raise AudioPipelineError("audio must not be empty.")
        if start_offset < 0:
            raise AudioPipelineError("start_offset must not be negative.")

    def _build_single_utterance(
        self,
        audio: bytes,
        asr_result: ASRResult,
        start_offset: float,
        *,
        diarization_segments: list[DiarizedSegment] | None = None,
        role_map: dict[str, AISpeakerRole] | None = None,
        learn_roles: bool = False,
    ) -> Utterance:
        languages = self._identify_languages(asr_result)
        role, speaker_id = self._resolve_role(
            audio,
            asr_result,
            diarization_segments=diarization_segments,
            role_map=role_map,
        )
        if learn_roles and speaker_id is not None:
            # What the speaker said can settle who they are (e.g. the ICR's
            # greeting); from then on their speech carries that role.
            learned = self._observe_speech(speaker_id, asr_result.transcript, None)
            if role == SpeakerRole.UNKNOWN and learned is not None:
                role = learned
        return self._create_utterance(asr_result, role, languages, start_offset)

    def _observe_speech(
        self, speaker_id: str, transcript: str, role: SpeakerRole | None
    ) -> SpeakerRole | None:
        try:
            learned = self._role_provider.observe_speech(
                speaker_id,
                transcript,
                role=_DOMAIN_TO_AI_ROLE[role] if role is not None else None,
            )
        except Exception:
            logger.exception("Role provider could not learn from speaker %r", speaker_id)
            return None
        domain_role = _AI_TO_DOMAIN_ROLE.get(learned) if learned is not None else None
        return None if domain_role in (None, SpeakerRole.UNKNOWN) else domain_role

    def _create_utterance(
        self,
        asr_result: ASRResult,
        role: SpeakerRole,
        languages: tuple[str, ...],
        start_offset: float,
    ) -> Utterance:
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

    def _transcribe(self, audio: bytes, language_hint: str | None = None) -> ASRResult:
        with _measured("asr"):
            if language_hint is None:
                result = self._asr_provider.transcribe(audio)
            else:
                result = self._asr_provider.transcribe(audio, language_hint=language_hint)
        if not isinstance(result, ASRResult):
            raise AudioPipelineError("ASR provider returned an invalid result.")
        if not isinstance(result.transcript, str) or not result.transcript.strip():
            raise EmptyTranscriptError("ASR provider returned an empty transcript.")
        if result.end_time < result.start_time:
            raise AudioPipelineError("ASR provider returned end_time before start_time.")
        return result

    def _identify_languages(self, asr_result: ASRResult) -> tuple[str, ...]:
        with _measured("language"):
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

    def _resolve_role(
        self,
        audio: bytes,
        asr_result: ASRResult,
        *,
        diarization_segments: list[DiarizedSegment] | None = None,
        role_map: dict[str, AISpeakerRole] | None = None,
    ) -> tuple[SpeakerRole, str | None]:
        """The role of the speaker who said most of asr_result, and that
        speaker's id (None when no speaker could be told apart)."""
        try:
            if diarization_segments is None or role_map is None:
                segments, roles = self._diarize(audio)
            else:
                segments, roles = diarization_segments, role_map
            speaker_id = self._dominant_speaker(segments, asr_result)
            return self._safe_domain_role(speaker_id, roles), speaker_id
        except (AudioPipelineError, DiarizationError):
            logger.warning(
                "Unable to resolve a reliable speaker role for ASR result; using UNKNOWN."
            )
            return SpeakerRole.UNKNOWN, None

    def _diarize(
        self, audio: bytes
    ) -> tuple[list[DiarizedSegment], dict[str, AISpeakerRole]]:
        with _measured("diarization"):
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

        return segments, {a.speaker_id: a.role for a in assignments}

    @staticmethod
    def _safe_domain_role(
        speaker_id: str, roles: dict[str, AISpeakerRole]
    ) -> SpeakerRole:
        ai_role = roles.get(speaker_id)
        role = _AI_TO_DOMAIN_ROLE.get(ai_role) if ai_role is not None else None
        if role is None:
            logger.warning(
                "Speaker %r has no usable role mapping; preserving UNKNOWN state.",
                speaker_id,
            )
            return SpeakerRole.UNKNOWN
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

@contextmanager
def _measured(provider: str) -> Iterator[None]:
    started = time.monotonic()
    try:
        yield
    except NoSpeechDetected:
        raise
    except Exception:
        PROVIDER_ERRORS.inc(provider)
        raise
    finally:
        PROVIDER_REQUEST_DURATION.observe(time.monotonic() - started, provider)


# Continuing an utterance: speech the time limit cut is joined back up, but
# an utterance never grows past this, so one is never kept open for good
# (e.g. when line noise hides every pause).
_MAX_CONTINUED_UTTERANCE_SECONDS = 30.0
# A word cut in half by a chunk boundary can be heard in both chunks; at most
# this many repeated words are dropped where two chunks meet.
_MAX_BOUNDARY_OVERLAP_WORDS = 3
_BOUNDARY_PUNCTUATION = string.punctuation + "।॥…“”‘’"


def _heard_language(languages: tuple[str, ...], detected_language: str) -> str:
    """The Indian language the text was identified as, if any, else the
    language the ASR reported. The text's identification is independent of
    the ASR's language hint, so it shows when a locked language is wrong."""
    for language in languages:
        if language in INDIC_LANGUAGES:
            return language
    return detected_language


def _can_continue(open_utterance: Utterance, utterance: Utterance) -> bool:
    # Diarization labels are per chunk, so only a resolved role can tell
    # speakers apart: two different known roles never merge.
    roles = {open_utterance.speaker_role, utterance.speaker_role} - {SpeakerRole.UNKNOWN}
    if len(roles) > 1:
        return False
    return utterance.end_time - open_utterance.start_time <= _MAX_CONTINUED_UTTERANCE_SECONDS


def _continue_utterance(open_utterance: Utterance, utterance: Utterance) -> Utterance:
    confidences = (open_utterance.confidence, utterance.confidence)
    return replace(
        open_utterance,
        transcript=_join_transcripts(open_utterance.transcript, utterance.transcript),
        speaker_role=(
            open_utterance.speaker_role
            if open_utterance.speaker_role != SpeakerRole.UNKNOWN
            else utterance.speaker_role
        ),
        languages=tuple(dict.fromkeys(open_utterance.languages + utterance.languages)),
        end_time=max(open_utterance.end_time, utterance.end_time),
        confidence=None if None in confidences else min(confidences),
    )


def _join_transcripts(previous: str, addition: str) -> str:
    """previous + addition, without repeating the words heard in both chunks
    ("calling about" + "about my" -> "calling about my")."""
    previous_words = previous.split()
    added_words = addition.split()
    longest = min(_MAX_BOUNDARY_OVERLAP_WORDS, len(previous_words), len(added_words))
    for size in range(longest, 0, -1):
        tail = [_boundary_key(word) for word in previous_words[-size:]]
        head = [_boundary_key(word) for word in added_words[:size]]
        if tail == head and all(tail):
            added_words = added_words[size:]
            break
    if not added_words:
        return previous
    return f"{previous.rstrip()} {' '.join(added_words)}"


def _boundary_key(word: str) -> str:
    return word.strip(_BOUNDARY_PUNCTUATION).casefold()
