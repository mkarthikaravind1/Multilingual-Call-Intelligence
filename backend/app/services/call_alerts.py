"""Alerts on live calls, beyond escalation: a complaint not asked about, a
severe category, a detection the model was unsure of, and poor audio.

Each is a fixed rule over what the call already stores. They are shown on
screen (the supervisor's live view and the executive's own call); nothing is
sent anywhere.
"""

import dataclasses
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.domain.call_alert import (
    CallAlert,
    CallAlertType,
    QuestionOutcome,
    QuestionOutcomeChoice,
)
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.services.live_state_store import InMemoryLiveStateStore, LiveStateStore

logger = logging.getLogger(__name__)

# How many of a call's latest audio chunks (with someone speaking in them)
# are remembered, and how many lines' transcription confidence is averaged.
AUDIO_CHUNKS_REMEMBERED = 6
AUDIO_LINES_AVERAGED = 5
_AUDIO_TTL_SECONDS = 4 * 3600.0


@dataclass(frozen=True)
class AlertRules:
    # A complaint not asked about this long after it was detected.
    uncovered_after_seconds: float = 60.0
    # Categories that always alert (compared without regard to case), and
    # any category whose name contains one of the words.
    high_severity_categories: frozenset[str] = frozenset({"hygiene"})
    high_severity_words: tuple[str, ...] = ("safety",)
    # A complaint detected with less confidence than this.
    low_confidence_below: float = 0.6
    # Poor audio: this many of the remembered chunks had speech nothing
    # could be made of, or the latest lines' average transcription
    # confidence (when the speech recogniser gives one) is below this.
    unrecognised_chunks: int = 3
    transcription_confidence_below: float = 0.6

    @staticmethod
    def from_settings(settings) -> "AlertRules":
        return AlertRules(
            uncovered_after_seconds=settings.alert_uncovered_after_seconds,
            high_severity_categories=frozenset(
                name.strip().casefold()
                for name in settings.alert_high_severity_categories.split(",")
                if name.strip()
            ),
            low_confidence_below=settings.alert_low_confidence_below,
            unrecognised_chunks=settings.alert_poor_audio_unrecognised_chunks,
            transcription_confidence_below=settings.alert_poor_audio_confidence_below,
        )


class CallAlertRepository(ABC):
    @abstractmethod
    def save(self, alert: CallAlert) -> None:
        """Insert the alert, or replace the one for its call, type and subject."""
        raise NotImplementedError

    @abstractmethod
    def list_for_calls(self, call_ids: Iterable[str]) -> dict[str, tuple[CallAlert, ...]]:
        """Every alert of each call (standing or cleared), oldest first.
        Calls without alerts are left out."""
        raise NotImplementedError


class InMemoryCallAlertRepository(CallAlertRepository):
    def __init__(self) -> None:
        self._alerts: dict[tuple[str, CallAlertType, str], CallAlert] = {}

    def save(self, alert: CallAlert) -> None:
        self._alerts[alert.call_id, alert.alert_type, alert.subject] = alert

    def list_for_calls(self, call_ids: Iterable[str]) -> dict[str, tuple[CallAlert, ...]]:
        wanted = set(call_ids)
        found: dict[str, list[CallAlert]] = {}
        for alert in sorted(self._alerts.values(), key=lambda a: a.raised_at):
            if alert.call_id in wanted:
                found.setdefault(alert.call_id, []).append(alert)
        return {call_id: tuple(alerts) for call_id, alerts in found.items()}


class CallAlertService:
    def __init__(
        self,
        repository: CallAlertRepository,
        live_state: LiveStateStore | None = None,
        rules: AlertRules = AlertRules(),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._live_state = live_state or InMemoryLiveStateStore()
        self._rules = rules
        self._clock = clock

    # --- Audio quality, as the stream reports it ---

    def note_audio(self, call_id: str, recognised: bool) -> None:
        """A chunk of audio with someone speaking in it was transcribed
        (recognised) or nothing could be made of it."""
        try:
            recent = list(self._live_state.get_json(_audio_key(call_id)) or [])
            recent = (recent + [bool(recognised)])[-AUDIO_CHUNKS_REMEMBERED:]
            self._live_state.set_json(_audio_key(call_id), recent, _AUDIO_TTL_SECONDS)
        except Exception:
            logger.exception("Could not note the audio quality of call %r", call_id)

    def _unrecognised_chunks(self, call_id: str) -> int:
        try:
            recent = self._live_state.get_json(_audio_key(call_id)) or []
        except Exception:
            logger.exception("Could not read the audio quality of call %r", call_id)
            return 0
        return sum(1 for recognised in recent if not recognised)

    # --- The alerts ---

    def refresh(
        self, conversation: Conversation, coverage: ConversationCoverage | None
    ) -> tuple[CallAlert, ...]:
        """Bring the call's alerts up to what is true now: raise the new
        ones, clear the ones that no longer hold. Returns all of them."""
        now = self._clock()
        call_id = conversation.call_id
        true_now = self._conditions(conversation, coverage, now)
        stored = {
            (alert.alert_type, alert.subject): alert
            for alert in self._repository.list_for_calls([call_id]).get(call_id, ())
        }
        for key, message in true_now.items():
            alert = stored.get(key)
            if alert is None or not alert.is_open:
                stored[key] = CallAlert(call_id, key[0], key[1], message, raised_at=now)
                self._repository.save(stored[key])
            elif alert.message != message:
                stored[key] = dataclasses.replace(alert, message=message)
                self._repository.save(stored[key])
        for key, alert in stored.items():
            if alert.is_open and key not in true_now:
                stored[key] = dataclasses.replace(alert, cleared_at=now)
                self._repository.save(stored[key])
        return tuple(sorted(stored.values(), key=lambda a: a.raised_at))

    def list_for_call(self, call_id: str) -> tuple[CallAlert, ...]:
        return self._repository.list_for_calls([call_id]).get(call_id, ())

    def list_for_calls(self, call_ids: Iterable[str]) -> dict[str, tuple[CallAlert, ...]]:
        return self._repository.list_for_calls(call_ids)

    def _conditions(
        self, conversation: Conversation, coverage: ConversationCoverage | None, now: float
    ) -> dict[tuple[CallAlertType, str], str]:
        rules = self._rules
        found: dict[tuple[CallAlertType, str], str] = {}
        for complaint in () if coverage is None else coverage.complaints:
            if complaint.status is ComplaintCoverageStatus.NOT_RAISED:
                continue
            category = complaint.category
            if (
                complaint.status is ComplaintCoverageStatus.DETECTED
                and complaint.detected_at is not None
                and now - complaint.detected_at >= rules.uncovered_after_seconds
            ):
                found[CallAlertType.UNCOVERED_CATEGORY, category] = (
                    f"The {category} complaint has not been asked about yet."
                )
            name = category.casefold()
            if name in rules.high_severity_categories or any(
                word in name for word in rules.high_severity_words
            ):
                found[CallAlertType.HIGH_SEVERITY_CATEGORY, category] = (
                    f"{category} is a high-severity complaint."
                )
            if (
                complaint.confidence is not None
                and complaint.confidence < rules.low_confidence_below
            ):
                found[CallAlertType.LOW_CONFIDENCE, category] = (
                    f"The {category} complaint was detected with low confidence "
                    f"({round(complaint.confidence * 100)}%)."
                )

        audio = self._poor_audio(conversation)
        if audio is not None:
            found[CallAlertType.POOR_AUDIO, ""] = audio
        return found

    def _poor_audio(self, conversation: Conversation) -> str | None:
        unrecognised = self._unrecognised_chunks(conversation.call_id)
        if unrecognised >= self._rules.unrecognised_chunks:
            return (
                f"Poor audio: nothing could be made of {unrecognised} of the last "
                f"{AUDIO_CHUNKS_REMEMBERED} stretches of speech."
            )
        confidences = [
            u.confidence for u in conversation.utterances[-AUDIO_LINES_AVERAGED:]
            if u.confidence is not None
        ]
        if len(confidences) >= 3:
            average = sum(confidences) / len(confidences)
            if average < self._rules.transcription_confidence_below:
                return (
                    f"Poor audio: the last lines were transcribed with low confidence "
                    f"({round(average * 100)}%)."
                )
        return None


def _audio_key(call_id: str) -> str:
    return f"audio_quality:{call_id}"


# ---- What executives do with suggested questions ----


class QuestionOutcomeRepository(ABC):
    @abstractmethod
    def save(self, outcome: QuestionOutcome) -> None:
        """Insert the outcome, or replace the one for its call and question."""
        raise NotImplementedError

    @abstractmethod
    def list_for_calls(self, call_ids: Iterable[str]) -> dict[str, tuple[QuestionOutcome, ...]]:
        """Each call's outcomes, oldest first; calls without any are left out."""
        raise NotImplementedError

    @abstractmethod
    def totals(self) -> tuple[int, int]:
        """(accepted, skipped) over every call."""
        raise NotImplementedError


class InMemoryQuestionOutcomeRepository(QuestionOutcomeRepository):
    def __init__(self) -> None:
        self._outcomes: dict[tuple[str, str], QuestionOutcome] = {}

    def save(self, outcome: QuestionOutcome) -> None:
        self._outcomes[outcome.call_id, outcome.question] = outcome

    def list_for_calls(self, call_ids: Iterable[str]) -> dict[str, tuple[QuestionOutcome, ...]]:
        wanted = set(call_ids)
        found: dict[str, list[QuestionOutcome]] = {}
        for outcome in sorted(self._outcomes.values(), key=lambda o: o.created_at):
            if outcome.call_id in wanted:
                found.setdefault(outcome.call_id, []).append(outcome)
        return {call_id: tuple(outcomes) for call_id, outcomes in found.items()}

    def totals(self) -> tuple[int, int]:
        return count_outcomes(self._outcomes.values())


def count_outcomes(outcomes: Iterable[QuestionOutcome]) -> tuple[int, int]:
    """(accepted, skipped)."""
    outcomes = tuple(outcomes)
    accepted = sum(1 for o in outcomes if o.outcome is QuestionOutcomeChoice.ACCEPTED)
    return accepted, len(outcomes) - accepted
