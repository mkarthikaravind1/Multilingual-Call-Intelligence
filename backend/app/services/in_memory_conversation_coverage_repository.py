from app.domain.conversation_coverage import ConversationCoverage
from app.services.conversation_coverage_repository import ConversationCoverageRepository

class InMemoryConversationCoverageRepository(ConversationCoverageRepository):
    def __init__(self) -> None:
        self._coverages: dict[str, ConversationCoverage] = {}

    def save(self, coverage: ConversationCoverage) -> None:
        self._coverages[coverage.call_id] = coverage

    def get(self, call_id: str) -> ConversationCoverage | None:
        return self._coverages.get(call_id)