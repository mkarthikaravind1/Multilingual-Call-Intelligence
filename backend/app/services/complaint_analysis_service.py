from app.ai.complaint.provider import ComplaintDetectionProvider
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage


class ComplaintAnalysisService:
    def __init__(self, provider: ComplaintDetectionProvider) -> None:
        self._provider = provider

    def analyze(
        self, conversation: Conversation, coverage: ConversationCoverage
    ) -> ConversationCoverage:
        if conversation.call_id != coverage.call_id:
            raise ValueError(
                f"Coverage for call {coverage.call_id!r} cannot be updated from "
                f"conversation {conversation.call_id!r}."
            )

        for detection in self._provider.detect(conversation):
            complaint = coverage.get_or_add(detection.category)
            # detect() is only valid from NOT_RAISED; any other status means the
            # complaint has already progressed and must be left as it is.
            if complaint.status is ComplaintCoverageStatus.NOT_RAISED:
                complaint.detect()

        return coverage