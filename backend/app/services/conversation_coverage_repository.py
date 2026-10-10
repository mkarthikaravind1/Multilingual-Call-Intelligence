from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.domain.conversation_coverage import ConversationCoverage

class ConversationCoverageRepository(ABC):
    @abstractmethod
    def save(self, coverage: ConversationCoverage) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, call_id: str) -> ConversationCoverage | None:
        raise NotImplementedError

    def get_many(self, call_ids: Iterable[str]) -> dict[str, ConversationCoverage]:
        """The coverage of each of these calls that has one. The stores
        below answer it in one read; this default reads them one by one."""
        found = {}
        for call_id in call_ids:
            coverage = self.get(call_id)
            if coverage is not None:
                found[call_id] = coverage
        return found