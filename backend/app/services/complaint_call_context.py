"""What a complaint card shows about the call a complaint came from: when
it started, which ICR took it, and what the customer said that raised it.

Read together for a page of complaints (one read of their calls), so the
complaints queue does not ask once per card.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.conversation import Conversation
from app.domain.user_repository import UserRepository
from app.domain.utterance import SpeakerRole
from app.services.call_service import CallService

# A line whose speaker is not known yet may well be the customer's.
_CUSTOMER_ROLES = frozenset({SpeakerRole.CUSTOMER, SpeakerRole.UNKNOWN})

# Enough for a card; the call page has the full transcript.
MAX_CUSTOMER_LINES = 10


@dataclass(frozen=True)
class ComplaintCallContext:
    call_started_at: float | None
    # None: no ICR answered the call (or the user no longer exists).
    icr_name: str | None
    # Category -> the customer's lines that raise it, in call order.
    customer_lines: dict[str, tuple[str, ...]]

    def lines_for(self, category: str) -> tuple[str, ...]:
        return self.customer_lines.get(category, ())


def _customer_lines(conversation: Conversation) -> dict[str, tuple[str, ...]]:
    lines: dict[str, list[str]] = {}
    for utterance in conversation.utterances:
        if utterance.speaker_role not in _CUSTOMER_ROLES:
            continue
        for category in utterance.complaint_categories:
            kept = lines.setdefault(category, [])
            if len(kept) < MAX_CUSTOMER_LINES:
                kept.append(utterance.transcript.strip())
    return {category: tuple(kept) for category, kept in lines.items()}


def complaint_call_contexts(
    call_ids: Iterable[str],
    call_service: CallService,
    users: UserRepository | None,
) -> dict[str, ComplaintCallContext]:
    """The context of each call that exists among call_ids, by call_id."""
    conversations = call_service.get_calls(call_ids)
    names: dict[str, str | None] = {}
    contexts = {}
    for call_id, conversation in conversations.items():
        user_id = conversation.executive_user_id
        if user_id is not None and user_id not in names:
            user = None if users is None else users.get_by_id(user_id)
            names[user_id] = None if user is None else user.name
        contexts[call_id] = ComplaintCallContext(
            # 0 is the "not recorded" default, not 1 January 1970.
            call_started_at=conversation.start_time or None,
            icr_name=None if user_id is None else names[user_id],
            customer_lines=_customer_lines(conversation),
        )
    return contexts
