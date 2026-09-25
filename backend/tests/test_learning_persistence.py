import pytest

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementType,
)
from app.domain.improvement_candidate_repository import (
    ImprovementCandidateRepository,
    InMemoryImprovementCandidateRepository,
)
from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_evidence_repository import (
    InMemoryLearningEvidenceRepository,
    LearningEvidenceRepository,
)
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_feedback_repository import (
    InMemoryLearningFeedbackRepository,
    LearningFeedbackRepository,
)
from app.domain.learning_observation import LearningObservation
from app.domain.learning_observation_repository import (
    InMemoryLearningObservationRepository,
    LearningObservationRepository,
)
from app.domain.learning_pattern import LearningPattern
from app.services.human_review_service import HumanReviewService
from app.services.improvement_candidate_service import ImprovementCandidateService
from app.services.learning_candidate_generation_service import (
    LearningCandidateGenerationService,
)
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_human_review_service import LearningHumanReviewService
from app.services.learning_observation_service import LearningObservationService

REVIEWED_AT = 1_700_000_100.0


def make_observation(observation_id: str = "obs-1") -> LearningObservation:
    return LearningObservation(
        observation_id=observation_id,
        call_id="call-1",
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI output.",
        predicted_value="Cost",
        confidence=0.9,
        created_at=100.0,
    )


def make_feedback(feedback_id: str = "fb-1") -> LearningFeedback:
    return LearningFeedback(
        feedback_id=feedback_id,
        observation_id="obs-1",
        feedback_type=FeedbackType.HUMAN_CORRECTION,
        corrected_value="Communication",
        outcome=None,
        created_at=200.0,
        call_id="call-1",
    )


def make_evidence(evidence_id: str = "ev-1") -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        call_id="call-1",
        evidence_type=EvidenceType.AI_PREDICTION,
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI predicted complaint_detection 'Cost'.",
        expected_value=None,
        actual_value="Cost",
        human_correction=None,
        created_at=100.0,
    )


def make_candidate(candidate_id: str = "cand-1") -> ImprovementCandidate:
    return ImprovementCandidate(
        candidate_id=candidate_id,
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Improve complaint detection",
        description="Recurring issue.",
        evidence=("ev-1", "ev-2"),
        occurrence_count=2,
        confidence=0.5,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=1_700_000_000.0,
    )


def make_pattern(pattern_id: str = "pattern-1") -> LearningPattern:
    return LearningPattern(
        pattern_id=pattern_id,
        component=LearningComponent.COMPLAINT_DETECTION,
        description="Recurring issue in complaint_detection.",
        occurrence_count=2,
        evidence_ids=["ev-1", "ev-2"],
        suggested_improvement="Improve the component.",
        created_at=100.0,
    )


CASES = [
    pytest.param(
        InMemoryLearningObservationRepository, make_observation, "observation_id", id="observation"
    ),
    pytest.param(InMemoryLearningFeedbackRepository, make_feedback, "feedback_id", id="feedback"),
    pytest.param(InMemoryLearningEvidenceRepository, make_evidence, "evidence_id", id="evidence"),
    pytest.param(
        InMemoryImprovementCandidateRepository, make_candidate, "candidate_id", id="candidate"
    ),
]


@pytest.mark.parametrize("repository_type, make, id_field", CASES)
def test_repository_saves_and_retrieves_record(repository_type, make, id_field):
    repository = repository_type()
    record = make()

    repository.save(record)

    assert repository.get(getattr(record, id_field)) == record


@pytest.mark.parametrize("repository_type, make, id_field", CASES)
def test_missing_record_returns_none(repository_type, make, id_field):
    assert repository_type().get("unknown") is None


@pytest.mark.parametrize("repository_type, make, id_field", CASES)
def test_empty_repository_lists_nothing(repository_type, make, id_field):
    assert repository_type().list_all() == ()


@pytest.mark.parametrize("repository_type, make, id_field", CASES)
def test_list_all_returns_every_stored_record(repository_type, make, id_field):
    repository = repository_type()
    first, second = make(f"{id_field}-a"), make(f"{id_field}-b")
    repository.save(first)
    repository.save(second)

    assert set(repository.list_all()) == {first, second}


@pytest.mark.parametrize("repository_type, make, id_field", CASES)
def test_saving_same_id_replaces_existing_record(repository_type, make, id_field):
    repository = repository_type()
    repository.save(make("same"))
    repository.save(make("same"))

    assert len(repository.list_all()) == 1


@pytest.mark.parametrize(
    "abstract_type, concrete_type",
    [
        (LearningObservationRepository, InMemoryLearningObservationRepository),
        (LearningFeedbackRepository, InMemoryLearningFeedbackRepository),
        (LearningEvidenceRepository, InMemoryLearningEvidenceRepository),
        (ImprovementCandidateRepository, InMemoryImprovementCandidateRepository),
    ],
)
def test_repository_interface_contract(abstract_type, concrete_type):
    with pytest.raises(TypeError):
        abstract_type()
    assert isinstance(concrete_type(), abstract_type)


def test_observation_service_uses_injected_repository():
    repository = InMemoryLearningObservationRepository()
    service = LearningObservationService(repository)

    recorded = service.record(
        observation_id="obs-1",
        call_id="call-1",
        component=LearningComponent.SENTIMENT_ANALYSIS,
        description="AI output.",
        predicted_value="NEGATIVE",
        confidence=0.9,
        created_at=100.0,
    )

    assert repository.get("obs-1") == recorded


def test_evidence_service_uses_injected_repository():
    repository = InMemoryLearningEvidenceRepository()
    service = LearningEvidenceService(repository)
    evidence = make_evidence()

    service.record(
        evidence_id=evidence.evidence_id,
        call_id=evidence.call_id,
        evidence_type=evidence.evidence_type,
        component=evidence.component,
        description=evidence.description,
        expected_value=evidence.expected_value,
        actual_value=evidence.actual_value,
        human_correction=evidence.human_correction,
        created_at=evidence.created_at,
    )

    assert repository.get("ev-1") == evidence
    assert service.list_all() == (evidence,)


def test_candidate_service_persists_when_repository_injected():
    repository = InMemoryImprovementCandidateRepository()

    candidate = ImprovementCandidateService(repository).create_candidate(
        make_pattern(), confidence=0.7
    )

    assert repository.get(candidate.candidate_id) == candidate


def test_candidate_service_still_works_without_repository():
    candidate = ImprovementCandidateService().create_candidate(make_pattern(), confidence=0.7)

    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW


@pytest.mark.parametrize(
    "action, expected",
    [
        ("approve", ImprovementReviewStatus.APPROVED),
        ("reject", ImprovementReviewStatus.REJECTED),
    ],
)
def test_reviewed_candidate_is_persisted_and_original_unchanged(action, expected):
    repository = InMemoryImprovementCandidateRepository()
    original = make_candidate()
    repository.save(original)
    review = LearningHumanReviewService(HumanReviewService(), repository)

    reviewed = getattr(review, action)(original, reviewed_at=REVIEWED_AT)

    stored = repository.get("cand-1")
    assert stored == reviewed
    assert stored is not None
    assert stored.status is expected
    assert stored.reviewed_at == REVIEWED_AT
    assert original.status is ImprovementReviewStatus.PENDING_REVIEW
    assert original.reviewed_at is None
    assert len(repository.list_all()) == 1


def test_failed_review_does_not_overwrite_stored_candidate():
    repository = InMemoryImprovementCandidateRepository()
    repository.save(make_candidate())
    review = LearningHumanReviewService(HumanReviewService(), repository)
    approved = review.approve(make_candidate(), reviewed_at=REVIEWED_AT)

    with pytest.raises(ValueError):
        review.reject(approved)

    assert repository.get("cand-1") == approved


def test_review_service_still_works_without_repository():
    reviewed = LearningHumanReviewService(HumanReviewService()).approve(
        make_candidate(), reviewed_at=REVIEWED_AT
    )

    assert reviewed.status is ImprovementReviewStatus.APPROVED


def test_generated_candidates_are_persisted_then_review_updates_them():
    repository = InMemoryImprovementCandidateRepository()
    generation = LearningCandidateGenerationService(ImprovementCandidateService(repository))
    review = LearningHumanReviewService(HumanReviewService(), repository)

    generated = generation.generate([make_pattern("p1"), make_pattern("p2")])
    reviewed = review.approve(generated[0], reviewed_at=max(c.created_at for c in generated) + 1)

    assert {c.candidate_id for c in repository.list_all()} == {c.candidate_id for c in generated}
    assert repository.get(generated[0].candidate_id) == reviewed
    stored_other = repository.get(generated[1].candidate_id)
    assert stored_other is not None
    assert stored_other.status is ImprovementReviewStatus.PENDING_REVIEW