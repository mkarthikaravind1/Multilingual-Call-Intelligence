from typing import Any

import pytest

from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewStatus,
)


def _candidate(**overrides):
    defaults:dict[str,Any] = dict(
        candidate_id="cand-1",
        proposed_name="Loyalty Program Confusion",
        description="Customers repeatedly confused about how loyalty points are earned.",
        evidence=("Customer asked why points didn't apply.",),
        occurrence_count=3,
        confidence=0.7,
    )
    defaults.update(overrides)
    return EmergingComplaintCandidate(**defaults)


def test_creates_candidate_with_defaults():
    candidate = _candidate()

    assert candidate.candidate_id == "cand-1"
    assert candidate.related_category is None
    assert candidate.status == EmergingComplaintReviewStatus.PENDING_REVIEW


def test_creates_candidate_with_related_category():
    candidate = _candidate(related_category="Communication")

    assert candidate.related_category == "Communication"


def test_creates_candidate_with_explicit_status():
    candidate = _candidate(status=EmergingComplaintReviewStatus.ACCEPTED)

    assert candidate.status == EmergingComplaintReviewStatus.ACCEPTED


def test_rejects_empty_candidate_id():
    with pytest.raises(ValueError, match="candidate_id"):
        _candidate(candidate_id="  ")


def test_rejects_empty_proposed_name():
    with pytest.raises(ValueError, match="proposed_name"):
        _candidate(proposed_name="")


def test_rejects_proposed_name_that_duplicates_existing_category():
    with pytest.raises(ValueError, match="COMPLAINT_CATEGORIES"):
        _candidate(proposed_name="Hygiene")


def test_rejects_empty_description():
    with pytest.raises(ValueError, match="description"):
        _candidate(description=" ")


def test_rejects_empty_evidence_tuple():
    with pytest.raises(ValueError, match="evidence"):
        _candidate(evidence=())


def test_rejects_evidence_with_blank_entries():
    with pytest.raises(ValueError, match="evidence"):
        _candidate(evidence=("Real evidence.", "   "))


def test_rejects_non_tuple_evidence():
    with pytest.raises(ValueError, match="evidence"):
        _candidate(evidence=["Real evidence."])  # type: ignore[arg-type]


@pytest.mark.parametrize("occurrence_count", [0, -1, True, 2.5])
def test_rejects_invalid_occurrence_count(occurrence_count):
    with pytest.raises(ValueError, match="occurrence_count"):
        _candidate(occurrence_count=occurrence_count)


def test_rejects_confidence_out_of_range():
    with pytest.raises(ValueError, match="confidence"):
        _candidate(confidence=1.5)


def test_rejects_non_numeric_confidence():
    with pytest.raises(TypeError, match="confidence"):
        _candidate(confidence="0.8")  # type: ignore[arg-type]


def test_rejects_boolean_confidence():
    with pytest.raises(TypeError, match="confidence"):
        _candidate(confidence=True)  # type: ignore[arg-type]


def test_rejects_unsupported_related_category():
    with pytest.raises(ValueError, match="related_category"):
        _candidate(related_category="Not A Real Category")


def test_rejects_non_enum_status():
    with pytest.raises(TypeError, match="status"):
        _candidate(status="accepted")  # type: ignore[arg-type]


def test_candidate_is_immutable():
    candidate = _candidate()

    with pytest.raises(Exception):
        candidate.confidence = 0.99  # type: ignore[misc]