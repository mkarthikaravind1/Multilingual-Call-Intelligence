from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.domain.conversation import Conversation, ConversationStatus

class ConversationRepository(ABC):
    @abstractmethod
    def add(self, conversation: Conversation) -> None:
        """Insert a new conversation.

        Raises ConversationAlreadyExistsError if its call_id is taken; the
        existing conversation is left untouched.
        """
        raise NotImplementedError

    @abstractmethod
    def save(self, conversation: Conversation) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, call_id: str) -> Conversation | None:
        raise NotImplementedError

    def get_many(self, call_ids: Iterable[str]) -> dict[str, Conversation]:
        """The conversations that exist among call_ids, by call_id. One
        get() per id here; stores that can, read them together."""
        found = {}
        for call_id in dict.fromkeys(call_ids):
            conversation = self.get(call_id)
            if conversation is not None:
                found[call_id] = conversation
        return found

    @abstractmethod
    def list_page(self, limit: int, offset: int) -> tuple[Conversation, ...]:
        """Newest-created conversations first."""
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def count_by_status(self) -> dict[ConversationStatus, int]:
        raise NotImplementedError