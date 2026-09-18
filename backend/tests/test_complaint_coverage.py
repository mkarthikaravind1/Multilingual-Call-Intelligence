import pytest

from app.domain.complaint_coverage import (
    ComplaintCoverage,
    ComplaintCoverageStatus,
)


def test_complaint_lifecycle() -> None:
    complaint = ComplaintCoverage("Turnaround Time")

    assert complaint.status == ComplaintCoverageStatus.NOT_RAISED

    complaint.detect()
    assert complaint.status == ComplaintCoverageStatus.DETECTED

    complaint.probe()
    assert complaint.status == ComplaintCoverageStatus.PROBED

    complaint.cover()
    assert complaint.status == ComplaintCoverageStatus.COVERED

    complaint.resolve()
    assert complaint.status == ComplaintCoverageStatus.RESOLVED


def test_unresolved_complaint() -> None:
    complaint = ComplaintCoverage("Communication")

    complaint.detect()
    complaint.probe()
    complaint.cover()
    complaint.mark_unresolved()

    assert complaint.status == ComplaintCoverageStatus.UNRESOLVED


def test_invalid_category() -> None:
    with pytest.raises(ValueError):
        ComplaintCoverage("Invalid Category")


def test_invalid_transition() -> None:
    complaint = ComplaintCoverage("Cost")

    with pytest.raises(ValueError):
        complaint.cover()


def test_resolved_complaint_cannot_change() -> None:
    complaint = ComplaintCoverage("Service Quality")

    complaint.detect()
    complaint.probe()
    complaint.cover()
    complaint.resolve()

    with pytest.raises(ValueError):
        complaint.mark_unresolved()