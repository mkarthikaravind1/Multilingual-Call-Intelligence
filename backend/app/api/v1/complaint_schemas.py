from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.call_customer import CallCustomerLink
from app.domain.complaint_lifecycle import ComplaintLifecycleStatus
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewStatus,
)
from app.services.complaint_lifecycle_service import ComplaintView
from app.services.emerging_complaint_service import DiscoveryRun


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Complaint lifecycle ---------------------------------------------------


class ComplaintEventResponse(_Response):
    status: ComplaintLifecycleStatus
    at: float
    # "system" for changes made by call analysis, otherwise the user's email.
    actor: str
    note: str | None


class ComplaintResponse(_Response):
    complaint_id: str
    call_id: str
    category: str
    status: ComplaintLifecycleStatus
    is_open: bool
    follow_up_required: bool
    customer_id: str | None
    # The call's customer as stored when they were identified (CRM name and
    # vehicle registration); null until known.
    customer_name: str | None = None
    vehicle_registration: str | None = None
    first_detected_at: float
    last_updated_at: float
    # Statuses a person can move the complaint to now.
    allowed_actions: list[ComplaintLifecycleStatus]
    events: list[ComplaintEventResponse]


class CallComplaintsResponse(BaseModel):
    call_id: str
    # None until the caller is matched to a CRM customer.
    customer_id: str | None
    complaints: list[ComplaintResponse]
    # The same customer's complaints from other calls, most recent first.
    customer_history: list[ComplaintResponse]


class ComplaintActionRequest(_Request):
    status: Literal["resolved", "unresolved"]
    note: str | None = Field(default=None, max_length=500)


def to_complaint_response(
    view: ComplaintView, customer: CallCustomerLink | None = None
) -> ComplaintResponse:
    record = view.record
    return ComplaintResponse(
        customer_name=None if customer is None else customer.customer_name,
        vehicle_registration=None if customer is None else customer.vehicle_registration,
        complaint_id=record.complaint_id,
        call_id=record.call_id,
        category=record.category,
        status=record.status,
        is_open=record.is_open,
        follow_up_required=record.follow_up_required,
        customer_id=record.customer_id,
        first_detected_at=record.first_detected_at,
        last_updated_at=record.last_updated_at,
        allowed_actions=list(record.allowed_actions()),
        events=[ComplaintEventResponse.model_validate(event) for event in view.events],
    )


# --- Emerging complaints -----------------------------------------------------


class EmergingComplaintResponse(_Response):
    candidate_id: str
    proposed_name: str
    description: str
    evidence: list[str]
    call_ids: list[str]
    occurrence_count: int
    confidence: float
    related_category: str | None
    status: EmergingComplaintReviewStatus
    first_seen_at: float
    last_seen_at: float
    reviewed_by: str | None
    reviewed_at: float | None
    review_note: str | None


class DiscoveryRunResponse(_Response):
    ran_at: float
    calls_scanned: int
    candidates_found: int
    new_candidates: int
    skipped_reason: str | None


class EmergingComplaintsResponse(BaseModel):
    candidates: list[EmergingComplaintResponse]
    # None until discovery has run since the server started.
    last_run: DiscoveryRunResponse | None


class ReviewEmergingComplaintRequest(_Request):
    decision: EmergingComplaintReviewStatus
    note: str | None = Field(default=None, max_length=500)


def to_emerging_complaint_response(
    candidate: EmergingComplaintCandidate,
) -> EmergingComplaintResponse:
    return EmergingComplaintResponse.model_validate(candidate)


def to_discovery_run_response(run: DiscoveryRun | None) -> DiscoveryRunResponse | None:
    return None if run is None else DiscoveryRunResponse.model_validate(run)
