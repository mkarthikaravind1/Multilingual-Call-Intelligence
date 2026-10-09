from app.ai.complaint.provider import ComplaintDetectionProvider
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.services.runtime_improvement_service import ComponentLearning

NO_COMPLAINTS_OUTPUT = "No complaints"


class ComplaintAnalysisService:
    def __init__(
        self,
        provider: ComplaintDetectionProvider,
        learning: ComponentLearning | None = None,
    ) -> None:
        self._provider = provider
        self._learning = learning

    def analyze(
        self, conversation: Conversation, coverage: ConversationCoverage
    ) -> ConversationCoverage:
        if conversation.call_id != coverage.call_id:
            raise ValueError(
                f"Coverage for call {coverage.call_id!r} cannot be updated from "
                f"conversation {conversation.call_id!r}."
            )

        contexts = self.guidance()
        # Approved guidance is passed only when there is some, so providers
        # written against the one-argument form keep working unchanged.
        detections = (
            self._provider.detect(conversation, contexts)
            if contexts
            else self._provider.detect(conversation)
        )
        return self.apply(conversation, coverage, detections, contexts)

    def guidance(self) -> tuple:
        """The approved learning guidance for complaint detection."""
        return self._learning.contexts() if self._learning is not None else ()

    def apply(
        self,
        conversation: Conversation,
        coverage: ConversationCoverage,
        detections: list,
        contexts: tuple = (),
    ) -> ConversationCoverage:
        """Record detections made with `contexts` (here or in a combined
        live-analysis request) on the call's coverage."""
        for detection in detections:
            complaint = coverage.get_or_add(detection.category)
            # detect() is only valid from NOT_RAISED; any other status means the
            # complaint has already progressed and must be left as it is.
            if complaint.status is ComplaintCoverageStatus.NOT_RAISED:
                complaint.detect()

        if self._learning is not None:
            self._learning.record_usage(
                conversation.call_id,
                contexts,
                ", ".join(sorted(d.category for d in detections)) or NO_COMPLAINTS_OUTPUT,
            )
        return coverage
