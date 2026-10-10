from dataclasses import dataclass, field, replace
from enum import Enum
from app.domain.utterance import Utterance

class ConversationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"


class CallDirection(str, Enum):
    """INBOUND: the customer called. OUTBOUND: an executive called the
    customer."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallPhase(str, Enum):
    """Where a call stands, as people see it."""

    # Ringing: the customer called and no executive has answered yet.
    INCOMING = "incoming"
    # Ringing: an executive is calling the customer.
    OUTGOING = "outgoing"
    CONNECTED = "connected"
    ON_HOLD = "on_hold"
    ENDED = "ended"


def call_phase(
    status: ConversationStatus,
    direction: CallDirection | None,
    answered: bool,
    on_hold: bool,
) -> CallPhase:
    """answered: an executive is on the call, or something has been said."""
    if status == ConversationStatus.COMPLETED:
        return CallPhase.ENDED
    if on_hold:
        return CallPhase.ON_HOLD
    if answered:
        return CallPhase.CONNECTED
    return CallPhase.OUTGOING if direction is CallDirection.OUTBOUND else CallPhase.INCOMING


@dataclass(frozen=True)
class HoldPeriod:
    """A stretch of a call the executive kept the customer on hold."""

    started_at: float
    # None while the hold is still on.
    ended_at: float | None = None

    @property
    def seconds(self) -> float:
        """How long it lasted; 0 while it is still on."""
        return 0.0 if self.ended_at is None else max(0.0, self.ended_at - self.started_at)


class ConversationAlreadyCompletedError(Exception):
    """Raised when something tries to mutate a call that has already ended
    (e.g. an utterance arriving after the status webhook completed the
    call). Distinct from ConversationNotFoundError: the call exists, it's
    just no longer open for new activity."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__(f"Call is already completed: {call_id!r}")


class CallOnHoldError(ValueError):
    """Raised when a line is added by hand to a call that is on hold:
    nothing said during a hold is part of the conversation."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__("The call is on hold. Resume it to carry on.")


class ConversationAlreadyExistsError(Exception):
    """Raised when a call is started with a call_id that is already in use.
    An existing call is never reset or replaced."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__(f"A call already exists with id: {call_id!r}")


class UtteranceNotLatestError(ValueError):
    """Raised when an utterance to be updated is no longer the call's
    latest one (another utterance was added after it)."""


@dataclass
class Conversation:
    """Represents one complete call, holding its utterances in chronological order."""

    call_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    start_time: float = 0.0
    end_time: float | None = None

    _utterances: list[Utterance] = field(default_factory=list)
    # Private: mutated only via add_utterance(), so ordering can't be bypassed.

    # Who took the call and where; None when it was not recorded (calls from
    # before these were kept, or a phone call nobody could be matched to).
    direction: CallDirection | None = None
    location_id: str | None = None
    executive_user_id: str | None = None
    # Each time the call was put on hold, oldest first (see hold()).
    holds: tuple[HoldPeriod, ...] = ()

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")

    def add_utterance(self, utterance: Utterance) -> None:
        if self.status == ConversationStatus.COMPLETED:
            raise ConversationAlreadyCompletedError(self.call_id)
        if self._utterances and utterance.start_time < self._utterances[-1].start_time:
            raise ValueError(
                f"Utterances must be chronological: new utterance starts at "
                f"{utterance.start_time}, last one starts at {self._utterances[-1].start_time}."
            )
        self._utterances.append(utterance)

    def replace_latest_utterance(self, utterance: Utterance) -> None:
        """Update the latest utterance in place (same utterance_id), e.g.
        when live speech continues it. Earlier utterances never change."""
        if self.status == ConversationStatus.COMPLETED:
            raise ConversationAlreadyCompletedError(self.call_id)
        if not self._utterances or self._utterances[-1].utterance_id != utterance.utterance_id:
            raise UtteranceNotLatestError(
                f"Utterance {utterance.utterance_id!r} is not the latest utterance of call {self.call_id!r}."
            )
        if len(self._utterances) > 1 and utterance.start_time < self._utterances[-2].start_time:
            raise ValueError(
                f"Utterances must be chronological: updated utterance starts at "
                f"{utterance.start_time}, the one before starts at {self._utterances[-2].start_time}."
            )
        self._utterances[-1] = utterance

    def replace_transcript(self, utterances: tuple[Utterance, ...]) -> None:
        """Replace every utterance, e.g. with the call transcribed again
        from its recording after it completed (so allowed in any status)."""
        if not utterances:
            raise ValueError("A transcript needs at least one utterance.")
        if any(b.start_time < a.start_time for a, b in zip(utterances, utterances[1:])):
            raise ValueError("Utterances must be chronological.")
        self._utterances = list(utterances)

    @property
    def utterances(self) -> tuple[Utterance, ...]:
        return tuple(self._utterances)

    @property
    def latest_utterance(self) -> Utterance | None:
        return self._utterances[-1] if self._utterances else None

    @property
    def utterance_count(self) -> int:
        return len(self._utterances)

    @property
    def duration(self) -> float | None:
        return None if self.end_time is None else self.end_time - self.start_time

    def rate_utterances(self, ratings) -> int:
        """Give lines their tone (UtteranceSentiment each). A line that is
        gone, or whose words have changed since it was rated, is skipped.
        Allowed in any status: a completed call's lines are rated after it.
        Returns how many lines were rated."""
        return self.annotate_utterances(ratings=ratings)

    def annotate_utterances(self, ratings=(), categories=()) -> int:
        """Give lines what an analysis found on them: their tone
        (UtteranceSentiment each) and the complaint categories they raise
        (UtteranceCategories each). A line that is gone, or whose words
        have changed since it was analysed, is skipped. Allowed in any
        status. Returns how many lines changed."""
        tones = {rating.utterance_id: rating for rating in ratings}
        raised = {entry.utterance_id: entry for entry in categories}
        changed = 0
        for index, utterance in enumerate(self._utterances):
            updated = utterance
            tone = tones.get(utterance.utterance_id)
            if tone is not None and tone.transcript == utterance.transcript:
                updated = replace(
                    updated, sentiment=tone.label, sentiment_confidence=tone.confidence
                )
            entry = raised.get(utterance.utterance_id)
            if entry is not None and entry.transcript == utterance.transcript:
                updated = replace(updated, complaint_categories=tuple(entry.categories))
            if updated != utterance:
                self._utterances[index] = updated
                changed += 1
        return changed

    def assign(self, executive_user_id: str, location_id: str | None = None) -> None:
        """Record who took the call, e.g. once a ringing phone call is
        answered. A location already on the call is kept."""
        self.executive_user_id = executive_user_id
        if self.location_id is None:
            self.location_id = location_id

    # ---- On hold ----

    @property
    def on_hold(self) -> bool:
        return bool(self.holds) and self.holds[-1].ended_at is None

    @property
    def hold_seconds(self) -> float:
        """The time spent on hold, in holds that have ended."""
        return sum(hold.seconds for hold in self.holds)

    @property
    def phase(self) -> CallPhase:
        answered = self.executive_user_id is not None or bool(self._utterances)
        return call_phase(self.status, self.direction, answered, self.on_hold)

    def hold(self, at: float) -> bool:
        """Put the call on hold. False when it already is."""
        if self.status == ConversationStatus.COMPLETED:
            raise ConversationAlreadyCompletedError(self.call_id)
        if self.on_hold:
            return False
        self.holds = (*self.holds, HoldPeriod(started_at=at))
        return True

    def resume(self, at: float) -> bool:
        """Take the call off hold. False when it is not on hold."""
        if not self.on_hold:
            return False
        held = self.holds[-1]
        self.holds = (*self.holds[:-1], replace(held, ended_at=max(at, held.started_at)))
        return True

    def complete(self, end_time: float) -> None:
        if end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")
        # A call that ends on hold: the hold ends with it.
        self.resume(end_time)
        self.end_time = end_time
        self.status = ConversationStatus.COMPLETED