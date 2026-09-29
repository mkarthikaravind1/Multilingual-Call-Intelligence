from abc import ABC, abstractmethod
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