from app.domain.conversation import Conversation
from app.services.conversation_repository import ConversationRepository

class InMemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}

    def save(self, conversation: Conversation) -> None:
        self._conversations[conversation.call_id] = conversation

    def get(self, call_id: str) -> Conversation | None:
        return self._conversations.get(call_id)