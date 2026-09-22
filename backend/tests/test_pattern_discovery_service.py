"""Tests for PatternDiscoveryService."""

from app.domain.learning_evidence import (
    EvidenceType,
    LearningComponent,
    LearningEvidence,
)
from app.domain.learning_pattern import LearningPattern
from app.services.pattern_discovery_service import PatternDiscoveryService


COMPONENT_A = LearningComponent.COMPLAINT_DETECTION
COMPONENT_B = LearningComponent.NEXT_QUESTION


def _make_evidence(
    evidence_id: str,
    component: LearningComponent = COMPONENT_A,
    description: str = "misclassified refund complaint",
    evidence_type: EvidenceType = EvidenceType.HUMAN_CORRECTION,
    call_id: str = "call-1",
    expected_value: str | None = "refund complaint",
    actual_value: str | None = "general complaint",
    human_correction: str | None = "refund complaint",
    created_at: float = 1_700_000_000.0,
) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        call_id=call_id,
        evidence_type=evidence_type,
        component=component,
        description=description,
        expected_value=expected_value,
        actual_value=actual_value,
        human_correction=human_correction,
        created_at=created_at,
    )


def test_repeated_evidence_creates_a_learning_pattern():
    evidence = [
        _make_evidence("evidence-1"),
        _make_evidence("evidence-2"),
    ]

    service = PatternDiscoveryService(evidence)
    patterns = service.discover_patterns()

    assert len(patterns) == 1
    assert isinstance(patterns[0], LearningPattern)
    assert patterns[0].component == COMPONENT_A


def test_single_evidence_does_not_create_a_pattern():
    evidence = [_make_evidence("evidence-1")]

    service = PatternDiscoveryService(evidence)
    patterns = service.discover_patterns()

    assert patterns == []


def test_multiple_components_create_separate_patterns():
    evidence = [
        _make_evidence(
            "evidence-1",
            component=COMPONENT_A,
            description="repeated issue A",
        ),
        _make_evidence(
            "evidence-2",
            component=COMPONENT_A,
            description="repeated issue A",
        ),
        _make_evidence(
            "evidence-3",
            component=COMPONENT_B,
            description="repeated issue B",
        ),
        _make_evidence(
            "evidence-4",
            component=COMPONENT_B,
            description="repeated issue B",
        ),
    ]

    service = PatternDiscoveryService(evidence)
    patterns = service.discover_patterns()

    assert len(patterns) == 2

    components_found = {pattern.component for pattern in patterns}

    assert components_found == {COMPONENT_A, COMPONENT_B}


def test_occurrence_count_is_correct():
    evidence = [
        _make_evidence("evidence-1"),
        _make_evidence("evidence-2"),
        _make_evidence("evidence-3"),
    ]

    service = PatternDiscoveryService(evidence)
    patterns = service.discover_patterns()

    assert len(patterns) == 1
    assert patterns[0].occurrence_count == 3


def test_evidence_ids_are_correct():
    evidence = [
        _make_evidence("evidence-1"),
        _make_evidence("evidence-2"),
        _make_evidence("evidence-3"),
    ]

    service = PatternDiscoveryService(evidence)
    patterns = service.discover_patterns()

    assert len(patterns) == 1
    assert set(patterns[0].evidence_ids) == {
        "evidence-1",
        "evidence-2",
        "evidence-3",
    }


def test_empty_evidence_returns_empty_list():
    service = PatternDiscoveryService([])

    patterns = service.discover_patterns()

    assert patterns == []


def test_different_descriptions_are_not_incorrectly_grouped():
    evidence = [
        _make_evidence(
            "evidence-1",
            description="misclassified refund intent",
        ),
        _make_evidence(
            "evidence-2",
            description="misclassified cancellation intent",
        ),
    ]

    service = PatternDiscoveryService(evidence)
    patterns = service.discover_patterns()

    assert patterns == []


def test_multiple_repeated_groups_produce_multiple_patterns():
    evidence = [
        _make_evidence(
            "evidence-1",
            component=COMPONENT_A,
            description="pattern one",
        ),
        _make_evidence(
            "evidence-2",
            component=COMPONENT_A,
            description="pattern one",
        ),
        _make_evidence(
            "evidence-3",
            component=COMPONENT_A,
            description="pattern two",
        ),
        _make_evidence(
            "evidence-4",
            component=COMPONENT_A,
            description="pattern two",
        ),
        _make_evidence(
            "evidence-5",
            component=COMPONENT_A,
            description="pattern two",
        ),
    ]

    service = PatternDiscoveryService(evidence)
    patterns = service.discover_patterns()

    assert len(patterns) == 2

    occurrence_counts = sorted(
        pattern.occurrence_count for pattern in patterns
    )

    assert occurrence_counts == [2, 3]
