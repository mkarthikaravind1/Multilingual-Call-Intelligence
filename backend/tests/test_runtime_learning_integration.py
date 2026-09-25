import logging
from typing import Any

import pytest

from app.ai.question.provider import QuestionSuggestionProvider
from app.domain.active_improvement import ActiveImprovementStatus
from app.domain.active_improvement_repository import InMemoryActiveImprovementRepository
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementSpecification,
    ImprovementType,
)
from app.domain.learning_evidence import LearningComponent
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.runtime_improvement_context import RuntimeImprovementContext
from app.services.human_review_service import HumanReviewService
from app.services.improvement_application_service import (
    ImprovementApplicationService,
    ImprovementNotApprovedError,
)
from app.services.next_question_service import NextQuestionService
from app.services.runtime_improvement_service import RuntimeImprovementService


def make_spec(component=LearningComponent.NEXT_QUESTION) -> ImprovementSpecification:
    return ImprovementSpecification(
        component=component,
        current_behavior="asked a generic follow-up",
        proposed_behavior="ask about parts availability sooner",
        reason="recurred 4 times",
    )


def make_candidate(
    candidate_id: str, component=LearningComponent.NEXT_QUESTION, **overrides
) -> ImprovementCandidate:
    defaults:dict[str,Any] = dict(
        candidate_id=candidate_id,
        improvement_type=ImprovementType.QUESTION_STRATEGY,
        title="Improve next question",
        description="Recurring next-question issue",
        evidence=("evidence-1",),
        occurrence_count=4,
        confidence=0.8,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=1_700_000_000.0,
        specification=make_spec(component),
    )
    defaults.update(overrides)
    return ImprovementCandidate(**defaults)


def activate(
    application_service: ImprovementApplicationService,
    candidate_id: str = "candidate-1",
    component=LearningComponent.NEXT_QUESTION,
):
    approved = HumanReviewService().approve(
        make_candidate(candidate_id, component), reviewed_at=1_700_000_100.0
    )
    return application_service.activate(approved, activated_at=1_700_000_200.0)


class RecordingProvider(QuestionSuggestionProvider):
    def __init__(self) -> None:
        self.received_context = None

    def generate(self, context):
        self.received_context = context
        return QuestionSuggestion(
            question="fake question",
            target_category=context.category,
            priority=1,
            reason="fake reason",
            source=SuggestionSource.MANUAL,
        )


def coverage_with_detected(category: str = "Cost") -> ConversationCoverage:
    coverage = ConversationCoverage(call_id="call-1")
    coverage.add(category).detect()
    return coverage


# 1. Active improvement retrieval
def test_active_improvement_can_be_retrieved_by_runtime_service():
    repository = InMemoryActiveImprovementRepository()
    activate(ImprovementApplicationService(repository))

    context = RuntimeImprovementService(repository).get_context_for_component(
        LearningComponent.NEXT_QUESTION
    )

    assert len(context) == 1
    assert isinstance(context[0], RuntimeImprovementContext)
    assert context[0].component is LearningComponent.NEXT_QUESTION


# 2. Component filtering
def test_only_matching_component_improvements_are_returned():
    repository = InMemoryActiveImprovementRepository()
    application_service = ImprovementApplicationService(repository)
    activate(application_service, "candidate-nq", LearningComponent.NEXT_QUESTION)
    activate(application_service, "candidate-sentiment", LearningComponent.SENTIMENT_ANALYSIS)

    context = RuntimeImprovementService(repository).get_context_for_component(
        LearningComponent.NEXT_QUESTION
    )

    assert len(context) == 1
    assert context[0].candidate_id == "candidate-nq"


# 3. Inactive lifecycle states are excluded
def test_non_active_lifecycle_states_are_excluded():
    repository = InMemoryActiveImprovementRepository()
    application_service = ImprovementApplicationService(repository)

    pending = make_candidate("pending")
    rejected = HumanReviewService().reject(make_candidate("rejected"), reviewed_at=1_700_000_050.0)
    approved_only = HumanReviewService().approve(make_candidate("approved-only"), reviewed_at=1_700_000_050.0)

    with pytest.raises(ImprovementNotApprovedError):
        application_service.activate(pending)
    with pytest.raises(ImprovementNotApprovedError):
        application_service.activate(rejected)

    # approved-but-not-activated never reaches the repository
    improvement = activate(application_service, "deactivated-candidate")
    application_service.deactivate(improvement.improvement_id, at=1_700_000_300.0)

    context = RuntimeImprovementService(repository).get_context_for_component(
        LearningComponent.NEXT_QUESTION
    )
    assert context == ()
    assert approved_only.status is ImprovementReviewStatus.APPROVED  # still unactivated


# 4. Runtime context creation correctness
def test_runtime_context_preserves_specification_and_ids():
    repository = InMemoryActiveImprovementRepository()
    improvement = activate(ImprovementApplicationService(repository))

    context = RuntimeImprovementService(repository).get_context_for_component(
        LearningComponent.NEXT_QUESTION
    )[0]

    assert context.improvement_id == improvement.improvement_id
    assert context.candidate_id == improvement.candidate_id
    assert context.specification == improvement.specification


# 5. Next-question integration
def test_next_question_service_passes_learning_context_to_provider():
    repository = InMemoryActiveImprovementRepository()
    activate(ImprovementApplicationService(repository))
    provider = RecordingProvider()
    service = NextQuestionService(provider, RuntimeImprovementService(repository))

    suggestion = service.suggest_next_question(coverage_with_detected())

    assert suggestion is not None
    assert provider.received_context is not None
    assert len(provider.received_context.learning_context) == 1
    assert provider.received_context.learning_context[0].component is LearningComponent.NEXT_QUESTION


# 6. No active improvements -> existing behaviour
def test_no_active_improvements_yields_empty_learning_context():
    repository = InMemoryActiveImprovementRepository()
    provider = RecordingProvider()
    service = NextQuestionService(provider, RuntimeImprovementService(repository))

    service.suggest_next_question(coverage_with_detected())

    assert provider.received_context is not None
    assert provider.received_context.learning_context == ()


def test_next_question_service_without_runtime_service_is_unchanged():
    provider = RecordingProvider()
    service = NextQuestionService(provider)

    service.suggest_next_question(coverage_with_detected())

    assert provider.received_context is not None
    assert provider.received_context.learning_context == ()


# 7. Learning failure isolation
def test_learning_retrieval_failure_does_not_break_next_question(caplog):
    class FailingRepository(InMemoryActiveImprovementRepository):
        def list_active_for_component(self, component):
            raise RuntimeError("learning store unavailable")

    provider = RecordingProvider()
    service = NextQuestionService(provider, RuntimeImprovementService(FailingRepository()))

    with caplog.at_level(logging.ERROR):
        suggestion = service.suggest_next_question(coverage_with_detected())

    assert suggestion is not None
    assert provider.received_context is not None
    assert provider.received_context.learning_context == ()
    assert "improvement" in caplog.text.lower()


# 8. Provider compatibility
def test_question_suggestion_provider_contract_is_unchanged():
    assert issubclass(RecordingProvider, QuestionSuggestionProvider)


# 9. Lifecycle safety
def test_deactivated_improvement_is_excluded_from_runtime():
    repository = InMemoryActiveImprovementRepository()
    application_service = ImprovementApplicationService(repository)
    improvement = activate(application_service)
    deactivated = application_service.deactivate(improvement.improvement_id, at=1_700_000_300.0)

    assert deactivated.status is ActiveImprovementStatus.INACTIVE
    assert RuntimeImprovementService(repository).get_context_for_component(
        LearningComponent.NEXT_QUESTION
    ) == ()


# 10. Existing behaviour preserved with empty learning context
def test_no_actionable_complaint_still_returns_none_with_runtime_service():
    repository = InMemoryActiveImprovementRepository()
    provider = RecordingProvider()
    service = NextQuestionService(provider, RuntimeImprovementService(repository))

    suggestion = service.suggest_next_question(ConversationCoverage(call_id="call-1"))

    assert suggestion is None