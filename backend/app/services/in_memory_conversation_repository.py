from app.domain.conversation import (
    Conversation,
    ConversationAlreadyExistsError,
    ConversationStatus,
)
from app.services.conversation_repository import ConversationRepository

class InMemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}

    def add(self, conversation: Conversation) -> None:
        # setdefault is a single atomic check-and-insert.
        stored = self._conversations.setdefault(conversation.call_id, conversation)
        if stored is not conversation:
            raise ConversationAlreadyExistsError(conversation.call_id)

    def save(self, conversation: Conversation) -> None:
        self._conversations[conversation.call_id] = conversation

    def get(self, call_id: str) -> Conversation | None:
        return self._conversations.get(call_id)

    def list_page(self, limit: int, offset: int) -> tuple[Conversation, ...]:
        # Dict insertion order is creation order (re-saves keep their slot).
        newest_first = list(reversed(self._conversations.values()))
        return tuple(newest_first[offset : offset + limit])

    def count(self) -> int:
        return len(self._conversations)

    def count_by_status(self) -> dict[ConversationStatus, int]:
        counts = {status: 0 for status in ConversationStatus}
        for conversation in self._conversations.values():
            counts[conversation.status] += 1
        return counts