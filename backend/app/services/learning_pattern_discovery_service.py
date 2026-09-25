from app.domain.learning_pattern import LearningPattern
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_signal_filter_service import LearningSignalFilterService
from app.services.pattern_discovery_service import PatternDiscoveryService


class LearningPatternDiscoveryService:
    """Reads stored evidence, keeps only improvement signals, and delegates
    grouping to the existing PatternDiscoveryService unchanged."""

    def __init__(
        self,
        evidence_service: LearningEvidenceService,
        signal_filter: LearningSignalFilterService | None = None,
    ) -> None:
        self._evidence_service = evidence_service
        self._signal_filter = signal_filter or LearningSignalFilterService()

    def discover(self) -> list[LearningPattern]:
        signals = self._signal_filter.filter(self._evidence_service.list_all())
        return PatternDiscoveryService(signals).discover_patterns()