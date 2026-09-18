from dataclasses import dataclass, field
from enum import Enum

from app.domain.utterance import Utterance

class ConversationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"

@dataclass
class Conversation:
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
        if self._utterances and utterance.start_time < self._utterances[-1].start_time:
            raise ValueError(
                "Utterances must be added in chronological order: "
                f"new utterance starts at {utterance.start_time}, "
                f"but the last utterance starts at {self._utterances[-1].start_time}."
            )
        self._utterances.append(utterance)

    @property
    def utterances(self) -> tuple[Utterance, ...]:
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
        if self.end_time is None:
            return None
        return self.end_time - self.start_time

    def complete(self, end_time: float) -> None:
        if end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")
        self.end_time = end_time
        self.status = ConversationStatus.COMPLETED