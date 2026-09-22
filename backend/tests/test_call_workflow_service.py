import dataclasses
from dataclasses import dataclass

import pytest

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.ai.question.provider import (
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_service import CallService
from app.services.call_workflow_service import CallAnalysisResult, CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
)
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)
from app.services.next_question_service import NextQuestionService
from app.services.sentiment_analysis_service import SentimentAnalysisService
from app.domain.service_estimate import ServiceEstimate
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.services.estimation_service import EstimationService
from app.domain.service_estimate import ServiceEstimate

CALL_ID = "call-1"

_TURNAROUND = ComplaintDetectionResult(
    "Turnaround Time", 0.93, "The vehicle was supposed to be ready yesterday."
)
_COMMUNICATION = ComplaintDetectionResult(
    "Communication", 0.87, "The customer said nobody called them."
)
_SENTIMENT = SentimentResult(
    SentimentLabel.NEGATIVE, 0.9, "The customer reported a delayed service."
)


class FakeComplaintProvider(ComplaintDetectionProvider):
    def __init__(
        self,
        *responses: list[ComplaintDetectionResult],
        error: Exception | None = None,
    ) -> None:
        self._responses = responses
        self._error = error
        self.calls = 0

    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        if not self._responses:
            return []
        return list(self._responses[min(self.calls, len(self._responses)) - 1])


class FakeSentimentProvider(SentimentAnalysisProvider):
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls = 0

    def analyze(self, conversation: Conversation) -> SentimentResult:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return _SENTIMENT


class FakeQuestionProvider(QuestionSuggestionProvider):
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.contexts: list[QuestionGenerationContext] = []

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        self.contexts.append(context)
        if self._error is not None:
            raise self._error
        return QuestionSuggestion(
            question=f"Can you tell me more about the {context.category.lower()} issue?",
            target_category=context.category,
            priority=1,
            reason=f"The {context.category} complaint is {context.status.value}.",
            source=SuggestionSource.RULE_BASED,
        )


@dataclass
class _Harness:
    workflow: CallWorkflowService
    call_service: CallService
    coverage_repository: InMemoryConversationCoverageRepository
    complaint_provider: FakeComplaintProvider
    sentiment_provider: FakeSentimentProvider
    question_provider: FakeQuestionProvider
    estimation_service: EstimationService


def _build(
    complaint_provider: FakeComplaintProvider | None = None,
    sentiment_provider: FakeSentimentProvider | None = None,
    question_provider: FakeQuestionProvider | None = None,
    start_call: bool = True,
) -> _Harness:
    complaint_provider = complaint_provider or FakeComplaintProvider()
    sentiment_provider = sentiment_provider or FakeSentimentProvider()
    question_provider = question_provider or FakeQuestionProvider()
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    if start_call:
        call_service.start_call(CALL_ID)
    coverage_repository = InMemoryConversationCoverageRepository()
    estimation_service = EstimationService(
        RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)
    )
    workflow = CallWorkflowService(
        call_service,
        coverage_repository,
        ConversationAnalysisService(
            ComplaintAnalysisService(complaint_provider),
            SentimentAnalysisService(sentiment_provider),
        ),
        NextQuestionService(question_provider),
        estimation_service,
    )
    return _Harness(
        workflow,
        call_service,
        coverage_repository,
        complaint_provider,
        sentiment_provider,
        question_provider,
        estimation_service,
    )


def _utterance(index: int) -> Utterance:
    return Utterance(
        utterance_id=str(index + 1),
        transcript=f"Customer statement {index + 1}.",
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=index * 5.0,
        end_time=index * 5.0 + 4.0,
    )


def _statuses(coverage: ConversationCoverage) -> dict[str, ComplaintCoverageStatus]:
    return {c.category: c.status for c in coverage.complaints}


def test_process_utterance_adds_utterance_to_the_call():
    harness = _build()

    harness.workflow.process_utterance(CALL_ID, _utterance(0))

    assert harness.call_service.get_call(CALL_ID).utterance_count == 1


def test_process_utterance_returns_sentiment():
    harness = _build()

    result = harness.workflow.process_utterance(CALL_ID, _utterance(0))

    assert isinstance(result, CallAnalysisResult)
    assert result.sentiment == _SENTIMENT


def test_process_utterance_returns_question_suggestion():
    harness = _build(complaint_provider=FakeComplaintProvider([_TURNAROUND]))

    result = harness.workflow.process_utterance(CALL_ID, _utterance(0))

    assert result.question_suggestion is not None
    assert result.question_suggestion.target_category == "Turnaround Time"


def test_question_provider_receives_updated_coverage_and_utterances():
    harness = _build(complaint_provider=FakeComplaintProvider([_TURNAROUND]))

    harness.workflow.process_utterance(CALL_ID, _utterance(0))

    context = harness.question_provider.contexts[0]
    assert context.category == "Turnaround Time"
    assert context.status is ComplaintCoverageStatus.DETECTED
    assert context.utterances == harness.call_service.get_call(CALL_ID).utterances


def test_coverage_is_created_lazily_and_saved():
    harness = _build(complaint_provider=FakeComplaintProvider([_TURNAROUND]))
    assert harness.coverage_repository.get(CALL_ID) is None

    result = harness.workflow.analyze_call(CALL_ID)

    saved = harness.coverage_repository.get(CALL_ID)
    assert saved is result.coverage
    assert saved is not None and saved.call_id == CALL_ID
    assert _statuses(saved) == {"Turnaround Time": ComplaintCoverageStatus.DETECTED}


def test_coverage_persists_across_multiple_utterances():
    harness = _build(
        complaint_provider=FakeComplaintProvider(
            [_TURNAROUND], [_TURNAROUND, _COMMUNICATION]
        )
    )

    first = harness.workflow.process_utterance(CALL_ID, _utterance(0))
    second = harness.workflow.process_utterance(CALL_ID, _utterance(1))

    assert _statuses(first.coverage) == {
        "Turnaround Time": ComplaintCoverageStatus.DETECTED,
        "Communication": ComplaintCoverageStatus.DETECTED,
    }
    assert second.coverage is first.coverage
    assert harness.coverage_repository.get(CALL_ID) is second.coverage
    assert harness.call_service.get_call(CALL_ID).utterance_count == 2


def test_existing_coverage_state_is_preserved():
    harness = _build(complaint_provider=FakeComplaintProvider([_TURNAROUND]))
    coverage = ConversationCoverage(call_id=CALL_ID)
    complaint = coverage.add("Turnaround Time")
    complaint.detect()
    complaint.probe()
    harness.coverage_repository.save(coverage)

    result = harness.workflow.process_utterance(CALL_ID, _utterance(0))

    assert result.coverage is coverage
    assert _statuses(result.coverage) == {
        "Turnaround Time": ComplaintCoverageStatus.PROBED
    }
    assert harness.question_provider.contexts[0].status is ComplaintCoverageStatus.PROBED


def test_no_suggestion_when_no_complaint_is_actionable():
    harness = _build()

    result = harness.workflow.process_utterance(CALL_ID, _utterance(0))

    assert result.question_suggestion is None
    assert harness.question_provider.contexts == []
    assert result.sentiment == _SENTIMENT


@pytest.mark.parametrize("operation", ["process_utterance", "analyze_call"])
def test_unknown_call_raises_conversation_not_found(operation):
    harness = _build(start_call=False)

    with pytest.raises(ConversationNotFoundError):
        if operation == "process_utterance":
            harness.workflow.process_utterance(CALL_ID, _utterance(0))
        else:
            harness.workflow.analyze_call(CALL_ID)

    assert harness.complaint_provider.calls == 0
    assert harness.sentiment_provider.calls == 0
    assert harness.coverage_repository.get(CALL_ID) is None


def test_complaint_provider_exception_propagates():
    harness = _build(
        complaint_provider=FakeComplaintProvider(error=RuntimeError("complaint failed"))
    )

    with pytest.raises(RuntimeError, match="complaint failed"):
        harness.workflow.process_utterance(CALL_ID, _utterance(0))


def test_sentiment_provider_exception_propagates():
    harness = _build(sentiment_provider=FakeSentimentProvider(RuntimeError("sentiment failed")))

    with pytest.raises(RuntimeError, match="sentiment failed"):
        harness.workflow.process_utterance(CALL_ID, _utterance(0))


def test_question_provider_exception_propagates_after_coverage_is_saved():
    harness = _build(
        complaint_provider=FakeComplaintProvider([_TURNAROUND]),
        question_provider=FakeQuestionProvider(RuntimeError("question failed")),
    )

    with pytest.raises(RuntimeError, match="question failed"):
        harness.workflow.process_utterance(CALL_ID, _utterance(0))

    saved = harness.coverage_repository.get(CALL_ID)
    assert saved is not None
    assert _statuses(saved) == {"Turnaround Time": ComplaintCoverageStatus.DETECTED}

def test_call_analysis_result_is_frozen():
    result = _build().workflow.process_utterance(CALL_ID, _utterance(0))

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.sentiment = _SENTIMENT  # type: ignore

def test_process_utterance_returns_service_estimate_for_known_issue():
    harness = _build()

    result = harness.workflow.process_utterance(
        CALL_ID,
        Utterance(
            utterance_id="1",
            transcript="I need an oil change for my vehicle.",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=4.0,
        ),
    )

    assert result.service_estimate is not None
    assert isinstance(result.service_estimate, ServiceEstimate)
    assert result.service_estimate.service_name == "Oil Change"


def test_process_utterance_returns_no_estimate_for_unknown_issue():
    harness = _build()

    result = harness.workflow.process_utterance(
        CALL_ID,
        Utterance(
            utterance_id="1",
            transcript="I have a question about my vehicle.",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=4.0,
        ),
    )

    assert result.service_estimate is None


def test_estimation_provider_exception_propagates():
    class FailingEstimationProvider(RuleBasedEstimationProvider):
        def estimate(self, issue: str):
            raise RuntimeError("estimation failed")

    call_service = CallService(
        ConversationService(InMemoryConversationRepository())
    )
    call_service.start_call(CALL_ID)

    estimation_service = EstimationService(
        FailingEstimationProvider(DEFAULT_PRICING_CONFIG)
    )

    harness = _build()

    workflow = CallWorkflowService(
        call_service,
        harness.coverage_repository,
        ConversationAnalysisService(
            ComplaintAnalysisService(harness.complaint_provider),
            SentimentAnalysisService(harness.sentiment_provider),
        ),
        NextQuestionService(harness.question_provider),
        estimation_service,
    )

    with pytest.raises(RuntimeError, match="estimation failed"):
        workflow.process_utterance(
            CALL_ID,
            Utterance(
                utterance_id="1",
                transcript="I need an oil change.",
                speaker_role=SpeakerRole.CUSTOMER,
                languages=("en",),
                start_time=0.0,
                end_time=4.0,
            ),
        )