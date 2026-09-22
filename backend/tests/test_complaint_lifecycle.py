from typing import Any

import pytest

from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus


def _record(**overrides) -> ComplaintLifecycleRecord:
    defaults:dict[str,Any] = dict(
        complaint_id="cmp-1",
        call_id="call-1",
        category="Hygiene",
        status=ComplaintLifecycleStatus.RAISED,
        first_detected_at=0.0,
        last_updated_at=0.0,
        follow_up_required=False,
    )
    defaults.update(overrides)
    return ComplaintLifecycleRecord(**defaults)


def test_full_valid_transition_sequence():
    record = _record()

    record = record.transition_to(ComplaintLifecycleStatus.DETECTED, at=1.0)
    record = record.transition_to(ComplaintLifecycleStatus.PROBED, at=2.0)
    record = record.transition_to(ComplaintLifecycleStatus.COVERED, at=3.0)
    record = record.transition_to(ComplaintLifecycleStatus.RESOLVED, at=4.0)
    record = record.transition_to(ComplaintLifecycleStatus.FOLLOW_UP, at=5.0, follow_up_required=True)

    assert record.status == ComplaintLifecycleStatus.FOLLOW_UP
    assert record.last_updated_at == 5.0
    assert record.follow_up_required is True


def test_unresolved_path_also_reaches_follow_up():
    record = _record(status=ComplaintLifecycleStatus.COVERED, last_updated_at=3.0)

    record = record.transition_to(ComplaintLifecycleStatus.UNRESOLVED, at=4.0)
    record = record.transition_to(ComplaintLifecycleStatus.FOLLOW_UP, at=5.0)

    assert record.status == ComplaintLifecycleStatus.FOLLOW_UP


def test_invalid_transition_raises():
    record = _record()

    with pytest.raises(ValueError):
        record.transition_to(ComplaintLifecycleStatus.COVERED, at=1.0)


def test_follow_up_is_terminal():
    record = _record(status=ComplaintLifecycleStatus.FOLLOW_UP, last_updated_at=5.0)

    with pytest.raises(ValueError):
        record.transition_to(ComplaintLifecycleStatus.RESOLVED, at=6.0)


def test_transition_does_not_mutate_original():
    record = _record()
    next_record = record.transition_to(ComplaintLifecycleStatus.DETECTED, at=1.0)

    assert record.status == ComplaintLifecycleStatus.RAISED
    assert next_record.status == ComplaintLifecycleStatus.DETECTED


def test_transition_timestamp_before_last_updated_rejected():
    record = _record(status=ComplaintLifecycleStatus.DETECTED, last_updated_at=5.0)

    with pytest.raises(ValueError):
        record.transition_to(ComplaintLifecycleStatus.PROBED, at=4.0)


def test_invalid_category_rejected():
    with pytest.raises(ValueError):
        _record(category="Not A Real Category")


def test_missing_ids_rejected():
    with pytest.raises(ValueError):
        _record(complaint_id="")

    with pytest.raises(ValueError):
        _record(call_id="  ")


def test_last_updated_before_first_detected_rejected():
    with pytest.raises(ValueError):
        _record(first_detected_at=5.0, last_updated_at=1.0)


def test_negative_timestamps_rejected():
    with pytest.raises(ValueError):
        _record(first_detected_at=-1.0, last_updated_at=-1.0)


def test_non_numeric_timestamp_rejected():
    with pytest.raises(TypeError):
        _record(first_detected_at="not a number")


def test_invalid_status_type_rejected():
    with pytest.raises(TypeError):
        _record(status="raised")


def test_follow_up_required_must_be_bool():
    with pytest.raises(TypeError):
        _record(follow_up_required="yes")

def test_transition_to_invalid_new_status_type_rejected():
    record = _record()

    with pytest.raises(TypeError):
        record.transition_to("detected", at=1.0)  # type: ignore

def test_blank_customer_id_is_rejected():
    with pytest.raises(ValueError):
        ComplaintLifecycleRecord(
            complaint_id="c1",
            call_id="call-1",
            category="Cost",
            status=ComplaintLifecycleStatus.RAISED,
            first_detected_at=0.0,
            last_updated_at=0.0,
            customer_id="   ",
        )


def test_customer_id_defaults_to_none():
    record = ComplaintLifecycleRecord(
        complaint_id="c1",
        call_id="call-1",
        category="Cost",
        status=ComplaintLifecycleStatus.RAISED,
        first_detected_at=0.0,
        last_updated_at=0.0,
    )
    assert record.customer_id is None