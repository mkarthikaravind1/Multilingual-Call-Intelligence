import socket
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
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import (
    ConversationAnalysisResult,
    ConversationAnalysisService,
)
from app.services.next_question_service import NextQuestionService
from app.services.sentiment_analysis_service import SentimentAnalysisService

CALL_ID = "call-1"

_SCRIPT = (
    (SpeakerRole.ICR, "How was your recent service experience?"),
    (
        SpeakerRole.CUSTOMER,
        "My vehicle was supposed to be ready yesterday, but I only got it today.",
    ),
    (SpeakerRole.ICR, "Did anyone inform you about the delay?"),
    (SpeakerRole.CUSTOMER, "No, nobody called me."),
)

_TURNAROUND = ComplaintDetectionResult(
    "Turnaround Time",
    0.93,
    "The customer said the vehicle was supposed to be ready yesterday but was only returned today.",
)
_COMMUNICATION = ComplaintDetectionResult(
    "Communication",
    0.87,
    "The customer said nobody called them about the delay.",
)
_DETECTED_CATEGORIES = {"Turnaround Time", "Communication"}
_SENTIMENT = SentimentResult(
    label=SentimentLabel.NEGATIVE,
    confidence=0.9,
    evidence="The customer reported a delayed service.",
)


class RecordingComplaintProvider(ComplaintDetectionProvider):
    def __init__(
        self, calls: list[str], results: list[ComplaintDetectionResult]
    ) -> None:
        self.calls = calls
        self.results = results
        self.received_conversation: Conversation | None = None

    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        self.calls.append("detect")
        self.received_conversation = conversation
        return list(self.results)


class RecordingSentimentProvider(SentimentAnalysisProvider):
    def __init__(self) -> None:
        self.received_conversation: Conversation | None = None

    def analyze(self, conversation: Conversation) -> SentimentResult:
        self.received_conversation = conversation
        return _SENTIMENT


class RecordingQuestionProvider(QuestionSuggestionProvider):
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.contexts: list[QuestionGenerationContext] = []

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        self.calls.append("generate")
        self.contexts.append(context)
        return QuestionSuggestion(
            question=f"Can you tell me more about the {context.category.lower()} issue?",
            target_category=context.category,
            priority=1,
            reason=f"The {context.category} complaint is {context.status.value}.",
            source=SuggestionSource.RULE_BASED,
        )


@dataclass
class _Run:
    conversation: Conversation
    coverage: ConversationCoverage
    detector: RecordingComplaintProvider
    question_provider: RecordingQuestionProvider
    calls: list[str]
    result: ConversationAnalysisResult
    question_suggestion: QuestionSuggestion | None


def _conversation() -> Conversation:
    conversation = Conversation(call_id=CALL_ID)
    for index, (role, text) in enumerate(_SCRIPT):
        conversation.add_utterance(
            Utterance(
                utterance_id=str(index + 1),
                transcript=text,
                speaker_role=role,
                languages=("en",),
                start_time=index * 5.0,
                end_time=index * 5.0 + 4.0,
            )
        )
    return conversation


def _run(
    coverage: ConversationCoverage, detections: list[ComplaintDetectionResult]
) -> _Run:
    calls: list[str] = []
    detector = RecordingComplaintProvider(calls, detections)
    question_provider = RecordingQuestionProvider(calls)
    analysis_service = ConversationAnalysisService(
        ComplaintAnalysisService(detector),
        SentimentAnalysisService(RecordingSentimentProvider()),
    )
    next_question_service = NextQuestionService(question_provider)

    conversation = _conversation()
    result = analysis_service.analyze(conversation, coverage)
    suggestion = next_question_service.suggest_next_question(
        result.coverage, conversation.utterances
    )
    return _Run(
        conversation, coverage, detector, question_provider, calls, result, suggestion
    )


def _statuses(coverage: ConversationCoverage) -> dict[str, ComplaintCoverageStatus]:
    return {c.category: c.status for c in coverage.complaints}


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("Network access is not allowed in this test.")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


@pytest.fixture
def new_call() -> _Run:
    return _run(ConversationCoverage(call_id=CALL_ID), [_TURNAROUND, _COMMUNICATION])


@pytest.fixture
def probed_call() -> _Run:
    coverage = ConversationCoverage(call_id=CALL_ID)
    complaint = coverage.add("Turnaround Time")
    complaint.detect()
    complaint.probe()
    return _run(coverage, [_TURNAROUND])


def test_detector_receives_the_full_conversation(new_call):
    assert new_call.detector.received_conversation is new_call.conversation
    assert new_call.conversation.utterance_count == len(_SCRIPT)


def test_analysis_result_includes_sentiment(new_call):
    assert new_call.result.sentiment == _SENTIMENT


def test_both_complaints_become_detected_and_are_not_advanced(new_call):
    assert _statuses(new_call.coverage) == {
        "Turnaround Time": ComplaintCoverageStatus.DETECTED,
        "Communication": ComplaintCoverageStatus.DETECTED,
    }


def test_coverage_contains_both_categories_and_is_updated_in_place(new_call):
    assert new_call.result.coverage is new_call.coverage
    assert {c.category for c in new_call.result.coverage.complaints} == _DETECTED_CATEGORIES


def test_next_question_engine_receives_updated_coverage(new_call):
    assert len(new_call.question_provider.contexts) == 1
    context = new_call.question_provider.contexts[0]
    assert context.category in _DETECTED_CATEGORIES
    assert context.status is ComplaintCoverageStatus.DETECTED
    assert context.utterances == new_call.conversation.utterances


def test_question_suggestion_targets_a_detected_actionable_complaint(new_call):
    suggestion = new_call.question_suggestion

    assert isinstance(suggestion, QuestionSuggestion)
    assert suggestion.target_category in _DETECTED_CATEGORIES
    assert suggestion.target_category == new_call.question_provider.contexts[0].category


def test_workflow_runs_detection_before_question_generation(new_call):
    assert new_call.calls == ["detect", "generate"]


def test_existing_probed_complaint_is_not_reset_by_repeated_detection(probed_call):
    assert _statuses(probed_call.coverage) == {
        "Turnaround Time": ComplaintCoverageStatus.PROBED
    }
    assert probed_call.detector.received_conversation is probed_call.conversation


def test_question_engine_sees_probed_status_for_existing_complaint(probed_call):
    context = probed_call.question_provider.contexts[0]
    suggestion = probed_call.question_suggestion

    assert probed_call.calls == ["detect", "generate"]
    assert context.category == "Turnaround Time"
    assert context.status is ComplaintCoverageStatus.PROBED
    assert suggestion is not None
    assert suggestion.target_category == "Turnaround Time"