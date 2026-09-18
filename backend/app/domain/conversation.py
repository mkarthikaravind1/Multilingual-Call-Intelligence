from dataclasses import dataclass, field
from enum import Enum
from app.domain.utterance import Utterance

class ConversationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"

@dataclass
class Conversation:
    """Represents one complete call, holding its utterances in chronological order."""

    call_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    start_time: float = 0.0
    end_time: float | None = None

    _utterances: list[Utterance] = field(default_factory=list)
    # Private: mutated only via add_utterance(), so ordering can't be bypassed.

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")

    def add_utterance(self, utterance: Utterance) -> None:
        if self._utterances and utterance.start_time < self._utterances[-1].start_time:
            raise ValueError(
                f"Utterances must be chronological: new utterance starts at "
                f"{utterance.start_time}, last one starts at {self._utterances[-1].start_time}."
            )
        self._utterances.append(utterance)

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

    def complete(self, end_time: float) -> None:
        if end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time.")
        self.end_time = end_time
        self.status = ConversationStatus.COMPLETED