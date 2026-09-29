import dataclasses
import inspect
from unittest.mock import create_autospec

import pytest

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementType,
)
from app.domain.improvement_candidate_repository import (
    InMemoryImprovementCandidateRepository,
)
from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_pattern import LearningPattern
from app.services import learning_candidate_generation_service as module
from app.services.improvement_candidate_service import ImprovementCandidateService
from app.services.learning_candidate_generation_service import (
    DEFAULT_CANDIDATE_CONFIDENCE,
    LearningCandidateGenerationService,
)


def make_pattern(
    pattern_id: str = "pattern-1",
    component: LearningComponent = LearningComponent.COMPLAINT_DETECTION,
    evidence_ids: list[str] | None = None,
) -> LearningPattern:
    ids = evidence_ids or ["e1", "e2"]
    return LearningPattern(
        pattern_id=pattern_id,
        component=component,
        description=f"Recurring issue in {component.value}.",
        occurrence_count=len(ids),
        evidence_ids=ids,
        suggested_improvement="Improve the component.",
        created_at=100.0,
    )


def build(**kwargs):
    return LearningCandidateGenerationService(ImprovementCandidateService(), **kwargs)


def test_pattern_generates_pending_candidate():
    pattern = make_pattern()

    candidates = build().generate([pattern])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, ImprovementCandidate)
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW
    assert candidate.reviewed_at is None
    assert candidate.improvement_type is ImprovementType.COMPLAINT_DETECTION
    assert candidate.title == "Improve complaint detection"
    assert candidate.description == pattern.description
    assert candidate.evidence == tuple(pattern.evidence_ids)
    assert candidate.occurrence_count == pattern.occurrence_count
    assert candidate.confidence == DEFAULT_CANDIDATE_CONFIDENCE


def test_multiple_patterns_generate_independent_candidates():
    patterns = [
        make_pattern("p1", LearningComponent.COMPLAINT_DETECTION, ["e1", "e2"]),
        make_pattern("p2", LearningComponent.NEXT_QUESTION, ["e3", "e4", "e5"]),
    ]

    candidates = build().generate(patterns)

    assert [c.improvement_type for c in candidates] == [
        ImprovementType.COMPLAINT_DETECTION,
        ImprovementType.QUESTION_STRATEGY,
    ]
    assert [c.evidence for c in candidates] == [("e1", "e2"), ("e3", "e4", "e5")]
    assert len({c.candidate_id for c in candidates}) == 2
    assert all(c.status is ImprovementReviewStatus.PENDING_REVIEW for c in candidates)


def test_no_patterns_produce_no_candidates():
    assert build().generate([]) == []


def test_existing_candidate_service_is_reused():
    candidate_service = create_autospec(ImprovementCandidateService, instance=True)
    pattern = make_pattern()
    service = LearningCandidateGenerationService(
        candidate_service, confidence_provider=lambda p: 0.8
    )

    result = service.generate([pattern])

    candidate_service.create_candidate.assert_called_once_with(pattern, confidence=0.8)
    assert result == [candidate_service.create_candidate.return_value]


def test_injected_confidence_provider_is_used():
    candidates = build(confidence_provider=lambda p: 0.9).generate([make_pattern()])

    assert candidates[0].confidence == 0.9


def test_candidates_are_never_approved_or_reviewed():
    candidates = build().generate([make_pattern(), make_pattern("p2")])

    assert all(c.status is ImprovementReviewStatus.PENDING_REVIEW for c in candidates)
    assert all(c.reviewed_at is None for c in candidates)


def test_human_review_service_is_not_involved():
    source = inspect.getsource(module)

    assert "HumanReviewService" not in source
    assert "human_review" not in source


def test_existing_candidate_service_remains_backward_compatible():
    pattern = make_pattern()

    candidate = ImprovementCandidateService().create_candidate(
        pattern, confidence=0.85, created_at=1_700_000_100.0
    )

    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW
    assert candidate.created_at == 1_700_000_100.0
    assert candidate.confidence == 0.85


def test_generation_does_not_modify_the_pattern():
    pattern = make_pattern()
    before = (
        pattern.pattern_id,
        pattern.component,
        pattern.description,
        pattern.occurrence_count,
        list(pattern.evidence_ids),
        pattern.suggested_improvement,
        pattern.created_at,
    )

    candidate = build().generate([pattern])[0]
    pattern.evidence_ids.append("e-extra")

    assert candidate.evidence == ("e1", "e2")
    assert before[4] == ["e1", "e2"]
    assert before[:4] == (
        pattern.pattern_id,
        pattern.component,
        pattern.description,
        pattern.occurrence_count,
    )


def test_non_pattern_input_is_rejected():
    with pytest.raises(TypeError):
        build().generate(["not a pattern"])  # type: ignore[list-item]


@pytest.mark.parametrize("confidence", [1.5, -0.1])
def test_invalid_confidence_is_rejected_by_existing_domain_validation(confidence):
    with pytest.raises(ValueError):
        build(confidence_provider=lambda p: confidence).generate([make_pattern()])


def test_pattern_without_improvement_mapping_is_rejected():
    with pytest.raises(ValueError, match="No ImprovementType mapping"):
        build().generate([make_pattern(component=LearningComponent.POST_CALL_SUMMARY)])


# ---- refresh(): runtime candidate generation from stored signals ----

CORRECTION = "AI predicted complaint_detection 'Turnaround Time' and human corrected it to 'Communication'."


def make_signal(
    evidence_id: str,
    description: str = CORRECTION,
    component: LearningComponent = LearningComponent.COMPLAINT_DETECTION,
) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        call_id=f"call-{evidence_id}",
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        component=component,
        description=description,
        expected_value="Communication",
        actual_value="Turnaround Time",
        human_correction="Communication",
        created_at=100.0,
    )


def refresher() -> tuple[LearningCandidateGenerationService, InMemoryImprovementCandidateRepository]:
    repository = InMemoryImprovementCandidateRepository()
    return build(repository=repository), repository


def review(repository, candidate, status):
    reviewed = dataclasses.replace(
        candidate, status=status, reviewed_at=candidate.created_at + 1.0
    )
    repository.save(reviewed)
    return reviewed


def test_refresh_creates_one_pending_candidate_per_pattern():
    service, repository = refresher()

    created = service.refresh([make_signal("e1"), make_signal("e2")])

    assert len(created) == 1
    (candidate,) = repository.list_all()
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW
    assert set(candidate.evidence) == {"e1", "e2"}
    assert candidate.improvement_type is ImprovementType.COMPLAINT_DETECTION
    assert candidate.specification is not None
    assert "Communication" in candidate.specification.current_behavior


def test_refresh_needs_a_repeated_signal():
    service, repository = refresher()

    assert service.refresh([make_signal("e1")]) == []
    assert repository.list_all() == ()


def test_refresh_is_idempotent():
    service, repository = refresher()
    signals = [make_signal("e1"), make_signal("e2")]
    service.refresh(signals)

    assert service.refresh(signals) == []
    assert len(repository.list_all()) == 1


def test_refresh_updates_the_pending_candidate_with_new_evidence():
    service, repository = refresher()
    service.refresh([make_signal("e1"), make_signal("e2")])
    (original,) = repository.list_all()

    service.refresh([make_signal("e1"), make_signal("e2"), make_signal("e3")])

    (refreshed,) = repository.list_all()
    assert refreshed.candidate_id == original.candidate_id
    assert refreshed.created_at == original.created_at
    assert refreshed.occurrence_count == 3
    assert set(refreshed.evidence) == {"e1", "e2", "e3"}
    assert "3 times" in refreshed.description


@pytest.mark.parametrize(
    "decision", [ImprovementReviewStatus.APPROVED, ImprovementReviewStatus.REJECTED]
)
def test_reviewed_evidence_is_not_proposed_again(decision):
    service, repository = refresher()
    service.refresh([make_signal("e1"), make_signal("e2")])
    reviewed = review(repository, repository.list_all()[0], decision)

    # One new correction is not enough for a new proposal.
    assert service.refresh([make_signal(i) for i in ("e1", "e2", "e3")]) == []
    assert repository.list_all() == (reviewed,)


def test_enough_new_evidence_after_a_review_makes_a_new_candidate():
    service, repository = refresher()
    service.refresh([make_signal("e1"), make_signal("e2")])
    reviewed = review(repository, repository.list_all()[0], ImprovementReviewStatus.REJECTED)

    (created,) = service.refresh([make_signal(i) for i in ("e1", "e2", "e3", "e4")])

    assert created.candidate_id != reviewed.candidate_id
    assert set(created.evidence) == {"e3", "e4"}
    assert created.status is ImprovementReviewStatus.PENDING_REVIEW
    assert repository.get(reviewed.candidate_id) == reviewed


def test_different_patterns_get_separate_candidates():
    service, repository = refresher()
    other = "AI predicted sentiment_analysis 'NEUTRAL' and human corrected it to 'NEGATIVE'."

    service.refresh(
        [
            make_signal("e1"),
            make_signal("e2"),
            make_signal("s1", other, LearningComponent.SENTIMENT_ANALYSIS),
            make_signal("s2", other, LearningComponent.SENTIMENT_ANALYSIS),
        ]
    )

    assert {c.improvement_type for c in repository.list_all()} == {
        ImprovementType.COMPLAINT_DETECTION,
        ImprovementType.SENTIMENT_ANALYSIS,
    }


def test_refresh_skips_patterns_without_an_improvement_type():
    service, repository = refresher()
    summary = "AI predicted post_call_summary 'x' and human corrected it to 'y'."

    created = service.refresh(
        [
            make_signal("p1", summary, LearningComponent.POST_CALL_SUMMARY),
            make_signal("p2", summary, LearningComponent.POST_CALL_SUMMARY),
            make_signal("e1"),
            make_signal("e2"),
        ]
    )

    assert [c.improvement_type for c in created] == [ImprovementType.COMPLAINT_DETECTION]


def test_refresh_requires_a_repository():
    with pytest.raises(RuntimeError, match="repository"):
        build().refresh([make_signal("e1"), make_signal("e2")])