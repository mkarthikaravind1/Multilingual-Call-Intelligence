# backend/app/services/complaint_lifecycle_integration_service.py

from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.complaint_lifecycle import ComplaintLifecycleStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.complaint_lifecycle_service import (
    ComplaintLifecycleNotFoundError,
    ComplaintLifecycleService,
)

# ComplaintCoverageStatus -> ComplaintLifecycleStatus. NOT_RAISED has no
# lifecycle equivalent, so it is intentionally omitted.
_COVERAGE_TO_LIFECYCLE: dict[ComplaintCoverageStatus, ComplaintLifecycleStatus] = {
    ComplaintCoverageStatus.DETECTED: ComplaintLifecycleStatus.DETECTED,
    ComplaintCoverageStatus.PROBED: ComplaintLifecycleStatus.PROBED,
    ComplaintCoverageStatus.COVERED: ComplaintLifecycleStatus.COVERED,
    ComplaintCoverageStatus.RESOLVED: ComplaintLifecycleStatus.RESOLVED,
    ComplaintCoverageStatus.UNRESOLVED: ComplaintLifecycleStatus.UNRESOLVED,
}

_PRE_BRANCH_ORDER = (
    ComplaintLifecycleStatus.DETECTED,
    ComplaintLifecycleStatus.PROBED,
    ComplaintLifecycleStatus.COVERED,
)


def _complaint_id_for(call_id: str, category: str) -> str:
    return f"{call_id}:{category}"


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
        self._sync_lifecycle(coverage, at)
        return coverage

    def _sync_lifecycle(self, coverage: ConversationCoverage, at: float) -> None:
        for complaint in coverage.complaints:
            target = _COVERAGE_TO_LIFECYCLE.get(complaint.status)
            if target is None:
                continue

            complaint_id = _complaint_id_for(coverage.call_id, complaint.category)

            try:
                record = self._complaint_lifecycle_service.get(complaint_id)
            except ComplaintLifecycleNotFoundError:
                self._complaint_lifecycle_service.create(
                    complaint_id=complaint_id,
                    call_id=coverage.call_id,
                    category=complaint.category,
                    first_detected_at=at,
                    status=target,
                )
                continue

            for step in self._steps_to(record.status, target):
                record = self._complaint_lifecycle_service.transition(
                    complaint_id=complaint_id,
                    call_id=coverage.call_id,
                    new_status=step,
                    at=at,
                )

    @staticmethod
    def _steps_to(
        current: ComplaintLifecycleStatus, target: ComplaintLifecycleStatus
    ) -> list[ComplaintLifecycleStatus]:
        if current == target:
            return []

        path: list[ComplaintLifecycleStatus] = list(_PRE_BRANCH_ORDER)
        if target in (ComplaintLifecycleStatus.RESOLVED, ComplaintLifecycleStatus.UNRESOLVED):
            path.append(target)

        target_index = path.index(target)
        start = path.index(current) + 1 if current in path else 0
        return path[start : target_index + 1]