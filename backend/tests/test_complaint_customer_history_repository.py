from app.domain.complaint_customer_history_repository import (
    InMemoryComplaintCustomerHistoryRepository,
)
from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus
from app.services.complaint_customer_history_service import ComplaintCustomerHistoryService


def make_record(
    complaint_id: str,
    call_id: str,
    customer_id: str | None,
    category: str = "Cost",
    status: ComplaintLifecycleStatus = ComplaintLifecycleStatus.RAISED,
    first_detected_at: float = 0.0,
) -> ComplaintLifecycleRecord:
    return ComplaintLifecycleRecord(
        complaint_id=complaint_id,
        call_id=call_id,
        category=category,
        status=status,
        first_detected_at=first_detected_at,
        last_updated_at=first_detected_at,
        customer_id=customer_id,
    )


def build_service():
    repository = InMemoryComplaintCustomerHistoryRepository()
    return ComplaintCustomerHistoryService(repository), repository


def test_saving_and_retrieving_a_complaint():
    service, _ = build_service()
    record = make_record("call-1:Cost", "call-1", "cust-1")

    service.save(record)

    assert service.get("call-1:Cost") == record


def test_multiple_complaints_for_one_customer():
    service, _ = build_service()
    record_a = make_record("call-1:Cost", "call-1", "cust-1", category="Cost")
    record_b = make_record("call-1:Hygiene", "call-1", "cust-1", category="Hygiene")

    service.save(record_a)
    service.save(record_b)

    history = service.get_history_for_customer("cust-1")
    assert set(history) == {record_a, record_b}


def test_retrieving_only_active_unresolved_complaints():
    service, _ = build_service()
    active = make_record("call-1:Cost", "call-1", "cust-1", status=ComplaintLifecycleStatus.DETECTED)
    closed = make_record(
        "call-1:Hygiene",
        "call-1",
        "cust-1",
        category="Hygiene",
        status=ComplaintLifecycleStatus.RESOLVED,
    )

    service.save(active)
    service.save(closed)

    assert service.get_active_for_customer("cust-1") == (active,)


def test_retrieving_history_across_multiple_call_ids():
    service, _ = build_service()
    first_call = make_record("call-1:Cost", "call-1", "cust-1", first_detected_at=0.0)
    second_call = make_record("call-2:Cost", "call-2", "cust-1", first_detected_at=10.0)

    service.save(first_call)
    service.save(second_call)

    history = service.get_history_for_customer("cust-1")
    assert history == (first_call, second_call)
    assert {record.call_id for record in history} == {"call-1", "call-2"}


def test_unknown_customer_returns_empty_result():
    service, _ = build_service()
    service.save(make_record("call-1:Cost", "call-1", "cust-1"))

    assert service.get_active_for_customer("cust-unknown") == ()
    assert service.get_history_for_customer("cust-unknown") == ()


def test_repository_isolation_between_customers():
    service, _ = build_service()
    record_a = make_record("call-1:Cost", "call-1", "cust-1")
    record_b = make_record("call-2:Cost", "call-2", "cust-2")

    service.save(record_a)
    service.save(record_b)

    assert service.get_history_for_customer("cust-1") == (record_a,)
    assert service.get_history_for_customer("cust-2") == (record_b,)