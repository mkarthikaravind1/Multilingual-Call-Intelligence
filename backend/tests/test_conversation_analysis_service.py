import ast
from pathlib import Path

import pytest

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.ai.question.provider import (
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.services import conversation_analysis_service as service_module
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import (
    ConversationAnalysisResult,
    ConversationAnalysisService,
)
from app.services.next_question_service import NextQuestionService


class FakeComplaintAnalysisService(ComplaintAnalysisService):
    def __init__(
        self,
        calls: list[str],
        updated: ConversationCoverage | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = calls
        self.updated = updated
        self.error = error
        self.received: tuple[Conversation, ConversationCoverage] | None = None

    def analyze(
        self, conversation: Conversation, coverage: ConversationCoverage
    ) -> ConversationCoverage:
        self.calls.append("complaint_analysis")
        self.received = (conversation, coverage)
        if self.error is not None:
            raise self.error
        return self.updated if self.updated is not None else coverage


class FakeNextQuestionService(NextQuestionService):
    def __init__(
        self,
        calls: list[str],
        suggestion: QuestionSuggestion | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = calls
        self.suggestion = suggestion
        self.error = error
        self.received_coverage: ConversationCoverage | None = None
        self.received_utterances: tuple[Utterance, ...] | None = None

    def suggest_next_question(
        self,
        coverage: ConversationCoverage,
        utterances: tuple[Utterance, ...] = (),
    ) -> QuestionSuggestion | None:
        self.calls.append("next_question")
        self.received_coverage = coverage
        self.received_utterances = utterances
        if self.error is not None:
            raise self.error
        return self.suggestion


class FakeComplaintProvider(ComplaintDetectionProvider):
    def __init__(self, results: list[ComplaintDetectionResult] | None = None) -> None:
        self.results = results or []
        self.call_count = 0

    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        self.call_count += 1
        return list(self.results)


class FakeQuestionProvider(QuestionSuggestionProvider):
    def __init__(self, suggestion: QuestionSuggestion | None = None) -> None:
        self.suggestion = suggestion
        self.contexts: list[QuestionGenerationContext] = []

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        self.contexts.append(context)
        return self.suggestion


def _suggestion(category: str = "Turnaround Time") -> QuestionSuggestion:
    return QuestionSuggestion(
        question="How many days late was the delivery?",
        target_category=category,
        priority=1,
        reason="The delay length is not known yet.",
        source=SuggestionSource.RULE_BASED,
    )


def _conversation() -> Conversation:
    return Conversation(call_id="call-1")


def _coverage(call_id: str = "call-1") -> ConversationCoverage:
    return ConversationCoverage(call_id=call_id)


def _service(
    calls: list[str],
    suggestion: QuestionSuggestion | None = None,
    updated: ConversationCoverage | None = None,
) -> tuple[ConversationAnalysisService, FakeComplaintAnalysisService, FakeNextQuestionService]:
    complaint = FakeComplaintAnalysisService(calls, updated=updated)
    question = FakeNextQuestionService(calls, suggestion=suggestion)
    return ConversationAnalysisService(complaint, question), complaint, question


def test_complaint_analysis_runs_before_next_question_generation():
    calls: list[str] = []
    service, _, _ = _service(calls)

    service.analyze(_conversation(), _coverage())

    assert calls == ["complaint_analysis", "next_question"]


def test_updated_coverage_is_passed_to_next_question_service():
    calls: list[str] = []
    updated = _coverage()
    service, _, question = _service(calls, updated=updated)

    result = service.analyze(_conversation(), _coverage())

    assert question.received_coverage is updated
    assert result.coverage is updated


def test_conversation_utterances_are_passed_to_next_question_service():
    conversation = _conversation()
    conversation.add_utterance(
        Utterance(
            utterance_id="1",
            transcript="The car was delivered two days late.",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    service, _, question = _service([])

    service.analyze(conversation, _coverage())

    assert question.received_utterances == conversation.utterances


def test_returned_question_suggestion_is_preserved():
    suggestion = _suggestion()
    service, _, _ = _service([], suggestion=suggestion)

    result = service.analyze(_conversation(), _coverage())

    assert isinstance(result, ConversationAnalysisResult)
    assert result.question_suggestion is suggestion


def test_no_available_question_returns_none_suggestion():
    coverage = _coverage()
    service, _, _ = _service([], suggestion=None)

    result = service.analyze(_conversation(), coverage)

    assert result.question_suggestion is None
    assert result.coverage is coverage


def test_injected_services_are_used_with_the_given_inputs():
    conversation = _conversation()
    coverage = _coverage()
    service, complaint, question = _service([])

    service.analyze(conversation, coverage)

    assert complaint.received == (conversation, coverage)
    assert question.received_coverage is coverage


def test_complaint_analysis_failure_propagates_and_skips_question_generation():
    calls: list[str] = []
    complaint = FakeComplaintAnalysisService(calls, error=RuntimeError("detector down"))
    question = FakeNextQuestionService(calls, suggestion=_suggestion())
    service = ConversationAnalysisService(complaint, question)

    with pytest.raises(RuntimeError, match="detector down"):
        service.analyze(_conversation(), _coverage())

    assert calls == ["complaint_analysis"]


def test_next_question_failure_propagates():
    calls: list[str] = []
    complaint = FakeComplaintAnalysisService(calls)
    question = FakeNextQuestionService(calls, error=RuntimeError("question failed"))
    service = ConversationAnalysisService(complaint, question)

    with pytest.raises(RuntimeError, match="question failed"):
        service.analyze(_conversation(), _coverage())

    assert calls == ["complaint_analysis", "next_question"]


def test_call_id_mismatch_is_rejected_by_complaint_analysis_service():
    calls: list[str] = []
    detector = FakeComplaintProvider()
    question = FakeNextQuestionService(calls, suggestion=_suggestion())
    service = ConversationAnalysisService(ComplaintAnalysisService(detector), question)

    with pytest.raises(ValueError, match="cannot be updated"):
        service.analyze(Conversation(call_id="a"), ConversationCoverage(call_id="b"))

    assert detector.call_count == 0
    assert calls == []


def test_existing_lifecycle_state_is_preserved_end_to_end():
    coverage = _coverage()
    complaint = coverage.add("Turnaround Time")
    complaint.detect()
    complaint.probe()
    detector = FakeComplaintProvider(
        [ComplaintDetectionResult("Turnaround Time", 0.9, "It was delivered late.")]
    )
    suggestion = _suggestion()
    question_provider = FakeQuestionProvider(suggestion)
    service = ConversationAnalysisService(
        ComplaintAnalysisService(detector), NextQuestionService(question_provider)
    )

    result = service.analyze(_conversation(), coverage)

    tracked = result.coverage.get("Turnaround Time")
    assert tracked is not None
    assert tracked.status is ComplaintCoverageStatus.PROBED
    assert result.question_suggestion is suggestion
    assert len(question_provider.contexts) == 1
    assert question_provider.contexts[0].category == "Turnaround Time"
    assert question_provider.contexts[0].status is ComplaintCoverageStatus.PROBED


def test_service_does_not_import_ai_or_groq_code():
    tree = ast.parse(Path(service_module.__file__).read_text())
    modules = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]

    assert not any(
        name.lower().startswith("app.ai") or "groq" in name.lower()
        for name in modules
    )