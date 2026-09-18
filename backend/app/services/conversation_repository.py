from abc import ABC, abstractmethod
from app.domain.conversation import Conversation

class ConversationRepository(ABC):
    @abstractmethod
    def save(self, conversation: Conversation) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, call_id: str) -> Conversation | None:
        raise NotImplementedError