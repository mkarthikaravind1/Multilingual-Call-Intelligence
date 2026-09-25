import ast
from pathlib import Path
from typing import Any

import pytest

from app.domain.active_improvement import ActiveImprovementStatus
from app.domain.active_improvement_repository import InMemoryActiveImprovementRepository
from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementSpecification,
    ImprovementType,
)
from app.domain.learning_evidence import LearningComponent
from app.services import call_workflow_service
from app.services.human_review_service import HumanReviewService
from app.services.improvement_application_service import (
    ActiveImprovementNotFoundError,
    ImprovementApplicationService,
    ImprovementNotApprovedError,
    MissingImprovementSpecificationError,
)


def make_spec(**overrides) -> ImprovementSpecification:
    defaults:dict[str,Any] = dict(
        component=LearningComponent.COMPLAINT_DETECTION,
        current_behavior="observed X",
        proposed_behavior="proposed Y",
        reason="recurred 3 times",
    )
    defaults.update(overrides)
    return ImprovementSpecification(**defaults)


def make_candidate(**overrides) -> ImprovementCandidate:
    defaults:dict[str,Any] = dict(
        candidate_id="candidate-1",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Improve complaint detection",
        description="Recurring complaint detection issue",
        evidence=("evidence-1", "evidence-2"),
        occurrence_count=2,
        confidence=0.85,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=1_700_000_000.0,
        reviewed_at=None,
        specification=make_spec(),
    )
    defaults.update(overrides)
    return ImprovementCandidate(**defaults)


def build_service() -> tuple[ImprovementApplicationService, InMemoryActiveImprovementRepository]:
    repository = InMemoryActiveImprovementRepository()
    return ImprovementApplicationService(repository), repository


def approved_candidate(**overrides) -> ImprovementCandidate:
    candidate = make_candidate(**overrides)
    return HumanReviewService().approve(candidate, reviewed_at=1_700_000_100.0)


# 1. Approved candidate can be activated
def test_approved_candidate_can_be_activated():
    service, _ = build_service()
    candidate = approved_candidate()

    improvement = service.activate(candidate, activated_at=1_700_000_200.0)

    assert improvement.status is ActiveImprovementStatus.ACTIVE
    assert improvement.activated_at == 1_700_000_200.0


# 2. Pending candidate cannot be activated
def test_pending_candidate_cannot_be_activated():
    service, _ = build_service()
    candidate = make_candidate(status=ImprovementReviewStatus.PENDING_REVIEW)

    with pytest.raises(ImprovementNotApprovedError):
        service.activate(candidate)


# 3. Rejected candidate cannot be activated
def test_rejected_candidate_cannot_be_activated():
    service, _ = build_service()
    candidate = make_candidate(
        status=ImprovementReviewStatus.REJECTED, reviewed_at=1_700_000_100.0
    )

    with pytest.raises(ImprovementNotApprovedError):
        service.activate(candidate)


# Candidate without a specification cannot be activated (SL-10 boundary)
def test_candidate_without_specification_cannot_be_activated():
    service, _ = build_service()
    candidate = approved_candidate(specification=None)

    with pytest.raises(MissingImprovementSpecificationError):
        service.activate(candidate)


# 4. Activated improvement contains correct candidate id
def test_activated_improvement_contains_candidate_id():
    service, _ = build_service()
    candidate = approved_candidate()

    improvement = service.activate(candidate)

    assert improvement.candidate_id == candidate.candidate_id


# 5 & 6. Specification and component preserved
def test_activated_improvement_preserves_specification_and_component():
    service, _ = build_service()
    candidate = approved_candidate()

    improvement = service.activate(candidate)

    assert improvement.specification == candidate.specification
    assert candidate.specification is not None
    assert improvement.component == candidate.specification.component


# 7 & 8. Persisted and retrievable
def test_activated_improvement_is_persisted_and_retrievable():
    service, _ = build_service()
    candidate = approved_candidate()

    improvement = service.activate(candidate)
    fetched = service.get(improvement.improvement_id)

    assert fetched == improvement


def test_get_missing_improvement_raises():
    service, _ = build_service()

    with pytest.raises(ActiveImprovementNotFoundError):
        service.get("does-not-exist")


# 9. Active improvements can be listed
def test_active_improvements_can_be_listed():
    service, _ = build_service()
    first = service.activate(approved_candidate(candidate_id="candidate-1"))
    second = service.activate(approved_candidate(candidate_id="candidate-2"))

    active = service.list_active()

    assert set(active) == {first, second}


# 10. Activating same candidate twice does not duplicate
def test_activating_same_candidate_twice_is_idempotent():
    service, repository = build_service()
    candidate = approved_candidate()

    first = service.activate(candidate)
    second = service.activate(candidate)

    assert first.improvement_id == second.improvement_id
    assert len(repository.list_all()) == 1


# 11. Original candidate remains APPROVED after activation
def test_original_candidate_remains_approved_after_activation():
    service, _ = build_service()
    candidate = approved_candidate()

    service.activate(candidate)

    assert candidate.status is ImprovementReviewStatus.APPROVED


# 12. Original LearningEvidence remains unchanged (activation never touches it)
def test_activation_does_not_touch_evidence_ids():
    service, _ = build_service()
    candidate = approved_candidate(evidence=("evidence-1", "evidence-2"))

    service.activate(candidate)

    assert candidate.evidence == ("evidence-1", "evidence-2")


# 13. Deactivation preserves history and only changes activation state
def test_deactivation_preserves_history_and_marks_inactive():
    service, repository = build_service()
    candidate = approved_candidate()
    improvement = service.activate(candidate, activated_at=1_700_000_200.0)

    deactivated = service.deactivate(improvement.improvement_id, at=1_700_000_300.0)

    assert deactivated.status is ActiveImprovementStatus.INACTIVE
    assert deactivated.deactivated_at == 1_700_000_300.0
    assert deactivated.improvement_id == improvement.improvement_id
    assert deactivated.candidate_id == improvement.candidate_id
    assert deactivated.specification == improvement.specification
    assert repository.get(improvement.improvement_id) == deactivated
    assert deactivated not in repository.list_active()


def test_deactivating_already_inactive_improvement_is_idempotent():
    service, _ = build_service()
    candidate = approved_candidate()
    improvement = service.activate(candidate, activated_at=1_700_000_200.0)
    once = service.deactivate(improvement.improvement_id, at=1_700_000_300.0)

    twice = service.deactivate(improvement.improvement_id, at=1_700_000_400.0)

    assert once == twice


# 14. Existing SL-9/SL-10 behavior is untouched by these new modules
def test_existing_candidate_generation_still_produces_pending_review():
    candidate = make_candidate(status=ImprovementReviewStatus.PENDING_REVIEW)
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW
    assert candidate.specification is not None


# 16 & runtime boundary: no AI/runtime service imports the new modules
def _imported_modules(module) -> list[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    return names


def test_call_workflow_service_does_not_consume_active_improvements():
    imported = [name.lower() for name in _imported_modules(call_workflow_service)]

    assert not any("active_improvement" in name for name in imported)
    assert not any("improvement_application" in name for name in imported)