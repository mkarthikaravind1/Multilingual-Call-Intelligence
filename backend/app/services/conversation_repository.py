from abc import ABC, abstractmethod
from app.domain.conversation import Conversation, ConversationStatus

class ConversationRepository(ABC):
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