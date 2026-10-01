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
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.services.next_question_service import NextQuestionService
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.sentiment_analysis_service import SentimentAnalysisService

from app.domain.customer_contact import ConsentStatus, CustomerContact
from app.domain.customer_summary_delivery import DeliveryStatus
from app.services.customer_summary_delivery_service import (
    CustomerSummaryDeliveryProvider,
    CustomerSummaryDeliveryService,
)
from app.services.customer_summary_repository import InMemoryCustomerSummaryDeliveryRepository
from app.services.post_call_summary_repository import InMemoryPostCallSummaryRepository

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
    post_call_summary_service: PostCallSummaryService


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
    post_call_summary_service = PostCallSummaryService(RuleBasedSummaryProvider())
    workflow = CallWorkflowService(
        call_service,
        coverage_repository,
        ConversationAnalysisService(
            ComplaintAnalysisService(complaint_provider),
            SentimentAnalysisService(sentiment_provider),
        ),
        NextQuestionService(question_provider),
        estimation_service,
        post_call_summary_service,
    )
    return _Harness(
        workflow,
        call_service,
        coverage_repository,
        complaint_provider,
        sentiment_provider,
        question_provider,
        estimation_service,
        post_call_summary_service,
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

    result = harness.workflow.process_utterance(CALL_ID, _utterance(0))

    saved = harness.coverage_repository.get(CALL_ID)
    assert saved is result.coverage
    assert saved is not None and saved.call_id == CALL_ID
    assert _statuses(saved) == {"Turnaround Time": ComplaintCoverageStatus.DETECTED}


def test_reading_an_active_call_before_any_speech_runs_no_providers():
    harness = _build(complaint_provider=FakeComplaintProvider([_TURNAROUND]))

    result = harness.workflow.analyze_call(CALL_ID)

    assert result.coverage.call_id == CALL_ID
    assert _statuses(result.coverage) == {}
    assert result.sentiment is None
    assert result.question_suggestion is None
    assert harness.complaint_provider.calls == 0
    assert harness.sentiment_provider.calls == 0
    assert harness.coverage_repository.get(CALL_ID) is None


def test_polling_an_active_call_returns_the_latest_analysis_without_provider_calls():
    harness = _build(complaint_provider=FakeComplaintProvider([_TURNAROUND]))
    live = harness.workflow.process_utterance(CALL_ID, _utterance(0))
    complaint_calls = harness.complaint_provider.calls
    sentiment_calls = harness.sentiment_provider.calls

    for _ in range(3):
        result = harness.workflow.analyze_call(CALL_ID)

    assert result.sentiment == live.sentiment
    assert result.question_suggestion == live.question_suggestion
    assert _statuses(result.coverage) == {"Turnaround Time": ComplaintCoverageStatus.DETECTED}
    assert harness.complaint_provider.calls == complaint_calls
    assert harness.sentiment_provider.calls == sentiment_calls


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
        harness.post_call_summary_service
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


# ---- Post-call completion workflow (Phase D) ----


class CountingSummaryProvider(RuleBasedSummaryProvider):
    def __init__(self, error: Exception | None = None, returns_none: bool = False) -> None:
        self._error = error
        self._returns_none = returns_none
        self.calls = 0

    def generate_summary(self, request):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._returns_none:
            return None
        return super().generate_summary(request)


class CountingNextQuestionService(NextQuestionService):
    def __init__(self, provider) -> None:
        super().__init__(provider)
        self.calls = 0

    def suggest_next_question(self, *args, **kwargs):
        self.calls += 1
        return super().suggest_next_question(*args, **kwargs)


class CountingCoverageRepository(InMemoryConversationCoverageRepository):
    def __init__(self) -> None:
        super().__init__()
        self.saves = 0

    def save(self, coverage):
        self.saves += 1
        super().save(coverage)


class FailingSummaryRepository(InMemoryPostCallSummaryRepository):
    def add_if_absent(self, summary):
        raise RuntimeError("database unavailable")


class RecordingDeliveryProvider(CustomerSummaryDeliveryProvider):
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.sent: list[str] = []

    def send_summary(self, contact, message, channel):
        if self._error is not None:
            raise self._error
        self.sent.append(message)
        return f"msg-{len(self.sent)}"


_CONTACT = CustomerContact(
    customer_id="cust-1",
    phone_number="+10000000000",
    consent_status=ConsentStatus.GRANTED,
)


@dataclass
class _PostCallHarness:
    workflow: CallWorkflowService
    call_service: CallService
    coverage_repository: CountingCoverageRepository
    summary_repository: InMemoryPostCallSummaryRepository
    summary_provider: CountingSummaryProvider
    complaint_provider: FakeComplaintProvider
    sentiment_provider: FakeSentimentProvider
    next_question_service: CountingNextQuestionService
    delivery_provider: RecordingDeliveryProvider
    delivery_repository: InMemoryCustomerSummaryDeliveryRepository


def _build_post_call(
    summary_provider: CountingSummaryProvider | None = None,
    summary_repository: InMemoryPostCallSummaryRepository | None = None,
    delivery_provider: RecordingDeliveryProvider | None = None,
    contact: CustomerContact | None = _CONTACT,
    customer_summary_enabled: bool = True,
) -> _PostCallHarness:
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    call_service.start_call(CALL_ID)
    complaint_provider = FakeComplaintProvider([_TURNAROUND])
    sentiment_provider = FakeSentimentProvider()
    next_question_service = CountingNextQuestionService(FakeQuestionProvider())
    coverage_repository = CountingCoverageRepository()
    summary_provider = summary_provider or CountingSummaryProvider()
    summary_repository = summary_repository or InMemoryPostCallSummaryRepository()
    delivery_provider = delivery_provider or RecordingDeliveryProvider()
    delivery_repository = InMemoryCustomerSummaryDeliveryRepository()
    workflow = CallWorkflowService(
        call_service,
        coverage_repository,
        ConversationAnalysisService(
            ComplaintAnalysisService(complaint_provider),
            SentimentAnalysisService(sentiment_provider),
        ),
        next_question_service,
        EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)),
        PostCallSummaryService(summary_provider),
        customer_summary_delivery_service=CustomerSummaryDeliveryService(
            delivery_provider, repository=delivery_repository
        ),
        customer_contact_resolver=lambda call_id: contact,
        post_call_summary_repository=summary_repository,
        customer_summary_enabled=customer_summary_enabled,
    )
    return _PostCallHarness(
        workflow,
        call_service,
        coverage_repository,
        summary_repository,
        summary_provider,
        complaint_provider,
        sentiment_provider,
        next_question_service,
        delivery_provider,
        delivery_repository,
    )


def _complete_with_speech(harness: _PostCallHarness, end_time: float = 30.0):
    harness.workflow.process_utterance(CALL_ID, _utterance(0))
    return harness.workflow.complete_call(CALL_ID, end_time)


def test_first_completion_generates_and_stores_summary():
    harness = _build_post_call()

    completion = _complete_with_speech(harness)

    assert completion.completed_now is True
    assert completion.conversation.status.value == "completed"
    stored = harness.summary_repository.get(CALL_ID)
    assert stored is not None
    assert stored.call_id == CALL_ID
    assert harness.summary_provider.calls == 1


def test_repeated_completion_keeps_end_time_and_does_not_reprocess():
    harness = _build_post_call()
    _complete_with_speech(harness, end_time=30.0)

    repeat = harness.workflow.complete_call(CALL_ID, 999.0)

    assert repeat.completed_now is False
    assert repeat.conversation.end_time == 30.0
    assert harness.call_service.get_call(CALL_ID).end_time == 30.0
    assert harness.summary_provider.calls == 1
    assert len(harness.delivery_provider.sent) == 1


def test_process_completed_call_does_not_regenerate_a_stored_summary():
    harness = _build_post_call()
    _complete_with_speech(harness)
    stored = harness.summary_repository.get(CALL_ID)

    again = harness.workflow.process_completed_call(CALL_ID)

    assert again is stored
    assert harness.summary_provider.calls == 1
    assert len(harness.delivery_provider.sent) == 1


def test_process_completed_call_ignores_active_calls():
    harness = _build_post_call()
    harness.workflow.process_utterance(CALL_ID, _utterance(0))

    assert harness.workflow.process_completed_call(CALL_ID) is None
    assert harness.summary_provider.calls == 0


def test_calls_without_utterances_get_no_summary():
    harness = _build_post_call()

    completion = harness.workflow.complete_call(CALL_ID, 5.0)

    assert completion.completed_now is True
    assert harness.summary_repository.get(CALL_ID) is None
    assert harness.summary_provider.calls == 0
    assert harness.delivery_provider.sent == []


@pytest.mark.parametrize(
    "summary_provider",
    [
        CountingSummaryProvider(error=RuntimeError("llm down")),
        CountingSummaryProvider(returns_none=True),
    ],
)
def test_summary_failure_keeps_call_completed_without_delivery(summary_provider):
    harness = _build_post_call(summary_provider=summary_provider)

    completion = _complete_with_speech(harness)

    assert completion.conversation.status.value == "completed"
    assert harness.call_service.get_call(CALL_ID).status.value == "completed"
    assert harness.summary_repository.get(CALL_ID) is None
    assert harness.delivery_provider.sent == []


def test_summary_persistence_failure_keeps_call_completed_without_delivery():
    harness = _build_post_call(summary_repository=FailingSummaryRepository())

    completion = _complete_with_speech(harness)

    assert completion.conversation.status.value == "completed"
    assert harness.summary_provider.calls == 1
    assert harness.delivery_provider.sent == []
    assert harness.delivery_repository.get_by_call_id(CALL_ID) == ()


def test_completed_call_analysis_is_read_only():
    harness = _build_post_call()
    _complete_with_speech(harness)
    stored = harness.summary_repository.get(CALL_ID)
    complaint_calls = harness.complaint_provider.calls
    sentiment_calls = harness.sentiment_provider.calls
    question_calls = harness.next_question_service.calls
    coverage_saves = harness.coverage_repository.saves

    result = harness.workflow.analyze_call(CALL_ID)

    assert result.post_call_summary is stored
    assert result.sentiment == stored.sentiment
    assert result.service_estimate == stored.service_estimate
    assert result.question_suggestion is None
    assert _statuses(result.coverage) == {"Turnaround Time": ComplaintCoverageStatus.DETECTED}
    assert harness.complaint_provider.calls == complaint_calls
    assert harness.sentiment_provider.calls == sentiment_calls
    assert harness.next_question_service.calls == question_calls
    assert harness.coverage_repository.saves == coverage_saves
    assert harness.summary_provider.calls == 1
    assert len(harness.delivery_provider.sent) == 1
    assert len(harness.delivery_repository.get_by_call_id(CALL_ID)) == 1


def test_completed_call_without_stored_summary_is_not_regenerated_on_read():
    harness = _build_post_call(summary_provider=CountingSummaryProvider(returns_none=True))
    _complete_with_speech(harness)
    provider_calls = harness.summary_provider.calls

    result = harness.workflow.analyze_call(CALL_ID)

    assert result.post_call_summary is None
    assert result.sentiment is None
    assert result.service_estimate is None
    assert result.question_suggestion is None
    assert harness.summary_provider.calls == provider_calls
    assert harness.summary_repository.get(CALL_ID) is None


def test_active_call_analysis_still_runs_live_analysis():
    harness = _build_post_call()
    harness.workflow.process_utterance(CALL_ID, _utterance(0))

    result = harness.workflow.analyze_call(CALL_ID)

    assert result.sentiment == _SENTIMENT
    assert result.question_suggestion is not None
    assert result.post_call_summary is None
    assert harness.summary_provider.calls == 0


def test_delivery_happens_only_after_summary_is_stored():
    harness = _build_post_call()

    _complete_with_speech(harness)

    (delivery,) = harness.delivery_repository.get_by_call_id(CALL_ID)
    assert delivery.status == DeliveryStatus.SENT
    assert delivery.call_id == CALL_ID
    assert harness.summary_repository.get(CALL_ID) is not None


def test_disabled_customer_summary_prevents_delivery():
    harness = _build_post_call(customer_summary_enabled=False)

    _complete_with_speech(harness)

    assert harness.summary_repository.get(CALL_ID) is not None
    assert harness.delivery_provider.sent == []
    assert harness.delivery_repository.get_by_call_id(CALL_ID) == ()


def test_delivery_still_enforces_consent():
    harness = _build_post_call(
        contact=CustomerContact(customer_id="cust-1", phone_number="+10000000000")
    )

    _complete_with_speech(harness)

    (delivery,) = harness.delivery_repository.get_by_call_id(CALL_ID)
    assert delivery.status == DeliveryStatus.REJECTED
    assert delivery.failure_reason == "customer_consent_missing"
    assert harness.delivery_provider.sent == []


def test_duplicate_delivery_is_prevented_by_idempotency():
    harness = _build_post_call()
    _complete_with_speech(harness)
    summary = harness.summary_repository.get(CALL_ID)

    delivery_service = CustomerSummaryDeliveryService(
        harness.delivery_provider, repository=harness.delivery_repository
    )
    repeat = delivery_service.send_summary_to_customer(summary=summary, contact=_CONTACT)

    assert repeat.status == DeliveryStatus.SENT
    assert len(harness.delivery_provider.sent) == 1
    assert len(harness.delivery_repository.get_by_call_id(CALL_ID)) == 1


def test_delivery_failure_is_recorded_and_call_stays_completed():
    harness = _build_post_call(
        delivery_provider=RecordingDeliveryProvider(error=RuntimeError("gateway down"))
    )

    completion = _complete_with_speech(harness)

    assert completion.conversation.status.value == "completed"
    assert harness.summary_repository.get(CALL_ID) is not None
    (delivery,) = harness.delivery_repository.get_by_call_id(CALL_ID)
    assert delivery.status == DeliveryStatus.FAILED
    assert delivery.failure_reason == "provider_delivery_failed"
