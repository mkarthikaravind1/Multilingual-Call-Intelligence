# backend/app/services/complaint_lifecycle_integration_service.py

from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.complaint_lifecycle_service import ComplaintLifecycleService


class ComplaintLifecycleIntegrationService:
    """Runs ComplaintAnalysisService unchanged, then syncs the resulting
    ConversationCoverage into ComplaintLifecycleService records."""

    def __init__(
        self,
        complaint_analysis_service: ComplaintAnalysisService,
        complaint_lifecycle_service: ComplaintLifecycleService,
    ) -> None:
        self._complaint_analysis_service = complaint_analysis_service
        self._complaint_lifecycle_service = complaint_lifecycle_service

    def analyze(
        self, conversation: Conversation, coverage: ConversationCoverage, at: float
    ) -> ConversationCoverage:
        coverage = self._complaint_analysis_service.analyze(conversation, coverage)
        self._complaint_lifecycle_service.sync_from_coverage(coverage, at)
        return coverage
