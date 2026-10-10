"""The latest live analysis of each active call, kept in the LiveStateStore
so every API instance reads the same thing.

Only the parts that cannot be read back from the database are stored:
sentiment, the next-question suggestion and the service estimate. Complaint
coverage and escalations stay in their own repositories, and transcripts
and audio are never stored here.

Each call also has a revision that changes whenever its live analysis
changes or the call completes, so a WebSocket on any instance can tell
cheaply when to push an update.

Store failures never fail a call: writes are logged and reads behave as if
nothing was stored, so callers fall back to what the database holds.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.service_estimate import (
    CallServiceEstimate,
    call_estimate_from_json,
    call_estimate_to_json,
)
from app.services.live_state_store import LiveStateStore

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 1
# Long enough for any call; refreshed by every new utterance.
DEFAULT_LIVE_ANALYSIS_TTL_SECONDS = 4 * 3600.0


@dataclass(frozen=True)
class LiveAnalysisSnapshot:
    sentiment: SentimentResult | None
    # The suggested questions, the most relevant first.
    question_suggestions: tuple[QuestionSuggestion, ...]
    service_estimate: CallServiceEstimate | None

    @property
    def question_suggestion(self) -> QuestionSuggestion | None:
        """The most relevant suggestion."""
        return self.question_suggestions[0] if self.question_suggestions else None


class LiveAnalysisStore:
    def __init__(
        self,
        store: LiveStateStore,
        ttl_seconds: float = DEFAULT_LIVE_ANALYSIS_TTL_SECONDS,
    ) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds

    def save(self, call_id: str, snapshot: LiveAnalysisSnapshot) -> None:
        try:
            self._store.set_json(
                _analysis_key(call_id), _serialize(snapshot), self._ttl_seconds
            )
        except Exception:
            logger.exception("Could not share the live analysis of call %r", call_id)
            return
        self.touch(call_id)

    def load(self, call_id: str) -> LiveAnalysisSnapshot | None:
        try:
            raw = self._store.get_json(_analysis_key(call_id))
        except Exception:
            logger.exception("Could not read the live analysis of call %r", call_id)
            return None
        if raw is None:
            return None
        try:
            return _deserialize(raw)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            logger.warning("Ignoring unreadable live analysis for call %r", call_id)
            return None

    def load_many(self, call_ids: Sequence[str]) -> dict[str, LiveAnalysisSnapshot]:
        """The latest live analysis of each of these calls that has one,
        in one read."""
        ids = list(call_ids)
        try:
            values = self._store.get_many_json([_analysis_key(call_id) for call_id in ids])
        except Exception:
            logger.exception("Could not read the live analysis of %d calls", len(ids))
            return {}
        found = {}
        for call_id, raw in zip(ids, values):
            if raw is None:
                continue
            try:
                found[call_id] = _deserialize(raw)
            except (KeyError, TypeError, ValueError, ArithmeticError):
                logger.warning("Ignoring unreadable live analysis for call %r", call_id)
        return found

    def forget(self, call_id: str) -> None:
        try:
            self._store.delete(_analysis_key(call_id))
        except Exception:
            logger.exception("Could not drop the live analysis of call %r", call_id)

    def touch(self, call_id: str) -> None:
        """Mark the call's live view as changed."""
        try:
            self._store.set_json(
                _revision_key(call_id), str(time.time_ns()), self._ttl_seconds
            )
        except Exception:
            logger.exception("Could not bump the live revision of call %r", call_id)

    def revision(self, call_id: str) -> str | None:
        try:
            value = self._store.get_json(_revision_key(call_id))
        except Exception:
            logger.exception("Could not read the live revision of call %r", call_id)
            return None
        return None if value is None else str(value)


def _analysis_key(call_id: str) -> str:
    return f"live_analysis:{call_id}"


def _revision_key(call_id: str) -> str:
    return f"live_revision:{call_id}"


def _serialize(snapshot: LiveAnalysisSnapshot) -> dict[str, Any]:
    sentiment = snapshot.sentiment
    estimate = snapshot.service_estimate
    return {
        "v": _FORMAT_VERSION,
        "sentiment": None
        if sentiment is None
        else {
            "label": sentiment.label.value,
            "confidence": sentiment.confidence,
            "evidence": sentiment.evidence,
        },
        # The first one alone as well: an instance still running the
        # version before the list reads that.
        "question_suggestion": _suggestion_to_json(snapshot.question_suggestion),
        "question_suggestions": [
            _suggestion_to_json(suggestion) for suggestion in snapshot.question_suggestions
        ],
        "service_estimate": None if estimate is None else call_estimate_to_json(estimate),
    }


def _suggestion_to_json(suggestion: QuestionSuggestion | None) -> dict[str, Any] | None:
    if suggestion is None:
        return None
    return {
        "question": suggestion.question,
        "target_category": suggestion.target_category,
        "priority": suggestion.priority,
        "reason": suggestion.reason,
        "source": suggestion.source.value,
        "confidence": suggestion.confidence,
        "language": suggestion.language,
        "question_en": suggestion.question_en,
    }


def _suggestion_from_json(suggestion: dict[str, Any]) -> QuestionSuggestion:
    return QuestionSuggestion(
        question=suggestion["question"],
        target_category=suggestion["target_category"],
        priority=suggestion["priority"],
        reason=suggestion["reason"],
        source=SuggestionSource(suggestion["source"]),
        confidence=suggestion["confidence"],
        language=suggestion.get("language", "en"),
        question_en=suggestion.get("question_en"),
    )


def _deserialize(data: dict[str, Any]) -> LiveAnalysisSnapshot:
    if data.get("v") != _FORMAT_VERSION:
        raise ValueError(f"Unsupported live analysis format {data.get('v')!r}.")
    sentiment = data["sentiment"]
    # Written before the list: the one question it had.
    suggestions = data.get("question_suggestions")
    if suggestions is None:
        suggestions = [] if data["question_suggestion"] is None else [data["question_suggestion"]]
    estimate = data["service_estimate"]
    return LiveAnalysisSnapshot(
        sentiment=None
        if sentiment is None
        else SentimentResult(
            label=SentimentLabel(sentiment["label"]),
            confidence=sentiment["confidence"],
            evidence=sentiment["evidence"],
        ),
        question_suggestions=tuple(_suggestion_from_json(s) for s in suggestions),
        service_estimate=None if estimate is None else call_estimate_from_json(estimate),
    )
