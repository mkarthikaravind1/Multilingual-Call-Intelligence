from abc import ABC, abstractmethod
from app.domain.conversation_coverage import ConversationCoverage

class ConversationCoverageRepository(ABC):
    @abstractmethod
    def save(self, coverage: ConversationCoverage) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, call_id: str) -> ConversationCoverage | None:
        raise NotImplementedError