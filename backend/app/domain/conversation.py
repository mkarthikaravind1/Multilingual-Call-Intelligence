from dataclasses import dataclass, field
from enum import Enum

from app.domain.utterance import Utterance


class ConversationStatus(str, Enum):
    """
    Simple lifecycle state for a conversation.

    Kept intentionally minimal (just ACTIVE/COMPLETED) per current
    business requirements. Richer states (processing, analyzed, failed,
    archived) belong to future service-layer workflows, not this domain
    model — adding them here now would be speculative, not needed yet.
    """
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass
class Conversation:
    """
    Represents one customer-service call: an ordered sequence of
    Utterances plus basic lifecycle metadata.

    This class only STORES conversation state — it performs no AI
    analysis (no sentiment, complaint detection, intent, etc). Those are
    separate service-layer concerns that will read a Conversation's
    utterances, not live inside it.

    Not frozen (unlike Utterance): a Conversation is a living object that
    grows over the life of a call and transitions between states, unlike
    an Utterance which represents one fact that already happened.
    """

    conversation_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    start_time: float = 0.0
    end_time: float | None = None
    # None means "not yet completed" — a conversation only has an
    # end_time once it's actually finished.

    _utterances: list[Utterance] = field(default_factory=list)
    # Private (leading underscore): callers must go through
    # add_utterance() to modify this list, so the chronological-order
    # invariant below can never be bypassed by direct list mutation.

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError("conversation_id must not be empty.")

        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")

    def add_utterance(self, utterance: Utterance) -> None:
        """
        Append an utterance to the conversation, enforcing chronological
        order.

        Rejecting out-of-order utterances (rather than silently
        re-sorting) surfaces upstream pipeline bugs immediately, instead
        of hiding them behind an automatic reorder that a caller might
        never notice.
        """
        if self._utterances and utterance.start_time < self._utterances[-1].start_time:
            raise ValueError(
                "Utterances must be added in chronological order: "
                f"new utterance starts at {utterance.start_time}, "
                f"but the last utterance starts at {self._utterances[-1].start_time}."
            )
        self._utterances.append(utterance)

    @property
    def utterances(self) -> tuple[Utterance, ...]:
        """
        Read-only view of all utterances, in chronological order.
        Returned as a tuple (not the internal list) so callers cannot
        mutate the conversation's utterances directly — they must use
        add_utterance().
        """
        return tuple(self._utterances)

    @property
    def latest_utterance(self) -> Utterance | None:
        """The most recent utterance, or None if the conversation is empty."""
        return self._utterances[-1] if self._utterances else None

    @property
    def utterance_count(self) -> int:
        return len(self._utterances)

    @property
    def duration(self) -> float | None:
        """
        Conversation duration in seconds, only available once the
        conversation has ended. Returns None while still active, rather
        than guessing a duration from the latest utterance's timestamp.
        """
        if self.end_time is None:
            return None
        return self.end_time - self.start_time

    def complete(self, end_time: float) -> None:
        """
        Marks the conversation as completed and records its end time.

        A dedicated method (rather than letting callers set `status` and
        `end_time` separately) keeps the two changes atomic and
        validated together — you can't end up with status=COMPLETED but
        end_time=None, or vice versa.
        """
        if end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")
        self.end_time = end_time
        self.status = ConversationStatus.COMPLETED