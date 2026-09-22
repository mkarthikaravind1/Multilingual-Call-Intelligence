import pytest

from app.domain.complaint_lifecycle import ComplaintLifecycleStatus
from app.domain.complaint_lifecycle_repository import InMemoryComplaintLifecycleRepository
from app.services.complaint_lifecycle_service import (
    ComplaintLifecycleCallMismatchError,
    ComplaintLifecycleNotFoundError,
    ComplaintLifecycleService,
)


def _service() -> ComplaintLifecycleService:
    return ComplaintLifecycleService(InMemoryComplaintLifecycleRepository())


def test_create_returns_and_persists_record():
    service = _service()

    record = service.create(
        complaint_id="cmp-1",
        call_id="call-1",
        category="Hygiene",
        first_detected_at=0.0,
    )

    assert record.status == ComplaintLifecycleStatus.RAISED
    assert record.complaint_id == "cmp-1"
    assert service.get("cmp-1") == record


def test_get_missing_complaint_raises():
    service = _service()

    with pytest.raises(ComplaintLifecycleNotFoundError):
        service.get("does-not-exist")


def test_valid_transition_updates_and_persists():
    service = _service()
    service.create(complaint_id="cmp-1", call_id="call-1", category="Hygiene", first_detected_at=0.0)

    updated = service.transition(
        complaint_id="cmp-1", call_id="call-1", new_status=ComplaintLifecycleStatus.DETECTED, at=1.0
    )

    assert updated.status == ComplaintLifecycleStatus.DETECTED
    assert updated.last_updated_at == 1.0
    assert service.get("cmp-1").status == ComplaintLifecycleStatus.DETECTED


def test_invalid_transition_propagates_domain_error():
    service = _service()
    service.create(complaint_id="cmp-1", call_id="call-1", category="Hygiene", first_detected_at=0.0)

    with pytest.raises(ValueError):
        service.transition(
            complaint_id="cmp-1", call_id="call-1", new_status=ComplaintLifecycleStatus.COVERED, at=1.0
        )


def test_transition_on_missing_complaint_raises():
    service = _service()

    with pytest.raises(ComplaintLifecycleNotFoundError):
        service.transition(
            complaint_id="does-not-exist",
            call_id="call-1",
            new_status=ComplaintLifecycleStatus.DETECTED,
            at=1.0,
        )


def test_transition_with_wrong_call_id_raises_mismatch():
    service = _service()
    service.create(complaint_id="cmp-1", call_id="call-1", category="Hygiene", first_detected_at=0.0)

    with pytest.raises(ComplaintLifecycleCallMismatchError):
        service.transition(
            complaint_id="cmp-1",
            call_id="wrong-call",
            new_status=ComplaintLifecycleStatus.DETECTED,
            at=1.0,
        )


def test_transition_does_not_mutate_previously_returned_record():
    service = _service()
    original = service.create(complaint_id="cmp-1", call_id="call-1", category="Hygiene", first_detected_at=0.0)

    service.transition(
        complaint_id="cmp-1", call_id="call-1", new_status=ComplaintLifecycleStatus.DETECTED, at=1.0
    )

    assert original.status == ComplaintLifecycleStatus.RAISED