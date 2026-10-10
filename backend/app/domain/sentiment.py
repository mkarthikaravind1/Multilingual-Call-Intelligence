from enum import Enum


class SentimentLabel(str, Enum):
    """The customer's tone: over a whole call, or on one line of it."""

    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    # Unhappy or dissatisfied.
    NEGATIVE = "NEGATIVE"
    # Annoyed or fed up: repeating themselves, losing patience.
    FRUSTRATED = "FRUSTRATED"
    # Anger is rising: threats, demands, refusing to go on.
    ESCALATING = "ESCALATING"

    @property
    def is_negative(self) -> bool:
        return self in _NEGATIVE_LABELS


_NEGATIVE_LABELS = frozenset(
    {SentimentLabel.NEGATIVE, SentimentLabel.FRUSTRATED, SentimentLabel.ESCALATING}
)
