from dataclasses import dataclass
from enum import Enum


class CallAlertType(str, Enum):
    # A complaint the executive has still not asked about.
    UNCOVERED_CATEGORY = "uncovered_category"
    # A complaint in a category marked as severe.
    HIGH_SEVERITY_CATEGORY = "high_severity_category"
    # A complaint the detector was not sure of.
    LOW_CONFIDENCE = "low_confidence"
    # The call's audio is hard to transcribe.
    POOR_AUDIO = "poor_audio"


@dataclass(frozen=True)
class CallAlert:
    """Something about a live call a supervisor should know. One per call,
    type and subject: it is raised when it becomes true, cleared when it no
    longer is, and raised again if it comes back. Kept with the call."""

    call_id: str
    alert_type: CallAlertType
    # What the alert is about: a complaint category, or "" for the call.
    subject: str
    message: str
    raised_at: float
    # None while the alert stands.
    cleared_at: float | None = None

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if not isinstance(self.alert_type, CallAlertType):
            raise TypeError("alert_type must be a CallAlertType.")
        if not self.message.strip():
            raise ValueError("An alert needs a message.")

    @property
    def is_open(self) -> bool:
        return self.cleared_at is None


class QuestionOutcomeChoice(str, Enum):
    ACCEPTED = "accepted"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class QuestionOutcome:
    """What the executive did with a suggested question. One per call and
    question: a later choice replaces the earlier one."""

    call_id: str
    question: str
    target_category: str
    outcome: QuestionOutcomeChoice
    user_id: str
    created_at: float

    def __post_init__(self) -> None:
        if not self.call_id.strip() or not self.question.strip():
            raise ValueError("A question outcome needs its call and its question.")
        if not isinstance(self.outcome, QuestionOutcomeChoice):
            raise TypeError("outcome must be a QuestionOutcomeChoice.")
