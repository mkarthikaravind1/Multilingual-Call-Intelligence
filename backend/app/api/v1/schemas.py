from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from app.ai.sentiment.provider import SentimentLabel
from app.domain.call_customer import CustomerMatchStatus
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.customer_contact import ConsentStatus, MessagingChannel
from app.domain.customer_summary_delivery import DeliveryStatus
from app.domain.escalation import EscalationLevel, EscalationSignalType, EscalationStatus
from app.domain.conversation import ConversationStatus
from app.domain.question_suggestion import SuggestionSource
from app.domain.utterance import SpeakerRole

class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class StartCallRequest(_Request):
    call_id: str = Field(min_length=1)
    start_time: float = 0.0
    # Optional: the customer's number when it is known up front.
    caller_number: str | None = Field(default=None, min_length=1, max_length=32)


class IdentifyCustomerRequest(_Request):
    phone_number: str = Field(min_length=1, max_length=32)


class SelectVehicleRequest(_Request):
    # None clears the choice.
    vehicle_id: str | None


class CustomerProfileResponse(_Response):
    customer_id: str
    name: str
    phone_number: str
    email: str | None
    preferred_channel: MessagingChannel
    consent_status: ConsentStatus
    language: str | None


class VehicleResponse(_Response):
    vehicle_id: str
    registration_number: str
    make: str
    model: str
    year: int | None
    vin: str | None


class ServiceRecordResponse(_Response):
    service_id: str
    vehicle_id: str
    service_date: str
    description: str
    dealer: str | None
    odometer_km: int | None


class CustomerSummaryDeliveryResponse(_Response):
    delivery_id: str
    customer_id: str
    channel: MessagingChannel
    # "sent" means accepted by the messaging provider, not yet confirmed
    # on the customer's handset.
    status: DeliveryStatus
    message: str
    provider: str | None
    provider_message_id: str | None
    attempts: int
    created_at: float
    updated_at: float
    failure_reason: str | None
    last_error: str | None


class CallSummaryDeliveriesResponse(BaseModel):
    call_id: str
    # Whether summaries are sent to customers at all (configuration).
    enabled: bool
    deliveries: list[CustomerSummaryDeliveryResponse]


class CallCustomerResponse(_Response):
    call_id: str
    status: CustomerMatchStatus
    caller_number: str | None
    customer: CustomerProfileResponse | None
    vehicles: list[VehicleResponse]
    selected_vehicle_id: str | None
    # For the selected vehicle, most recent first.
    service_history: list[ServiceRecordResponse]

class UtteranceRequest(_Request):
    utterance_id: str = Field(min_length=1)
    transcript: str = Field(min_length=1)
    speaker_role: SpeakerRole
    languages: list[str] = Field(min_length=1)
    start_time: float
    end_time: float
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

class CompleteCallRequest(_Request):
    end_time: float

class UtteranceResponse(_Response):
    utterance_id: str
    transcript: str
    speaker_role: SpeakerRole
    languages: list[str]
    start_time: float
    end_time: float
    confidence: float | None

class CallResponse(_Response):
    call_id: str
    status: ConversationStatus
    start_time: float
    end_time: float | None
    utterance_count: int
    utterances: list[UtteranceResponse]

class CallSummaryResponse(_Response):
    call_id: str
    status: ConversationStatus
    start_time: float
    end_time: float | None
    utterance_count: int
    # null when the call never escalated
    escalation_level: EscalationLevel | None = None
    escalation_status: EscalationStatus | None = None
    # Who the call was with; null until known. The name and registration
    # are the CRM's, stored when the customer was identified.
    caller_number: str | None = None
    customer_name: str | None = None
    vehicle_registration: str | None = None
    # When the last of the call's complaints was resolved (epoch seconds);
    # null while any is open, or when the call raised none.
    complaints_resolved_at: float | None = None

class CallListResponse(BaseModel):
    items: list[CallSummaryResponse]
    total: int
    limit: int
    offset: int

class CallStatsResponse(BaseModel):
    total: int
    active: int
    completed: int

class ComplaintCoverageResponse(_Response):
    category: str
    status: ComplaintCoverageStatus

class CoverageResponse(_Response):
    call_id: str
    complaints: list[ComplaintCoverageResponse]

class SentimentResponse(_Response):
    label: SentimentLabel
    confidence: float
    evidence: str

class QuestionSuggestionResponse(_Response):
    question: str
    target_category: str
    priority: int
    reason: str
    source: SuggestionSource
    confidence: float | None

class EstimatedPartResponse(_Response):
    name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal

class LabourEstimateResponse(_Response):
    hours: float
    hourly_rate: Decimal
    total_cost: Decimal

class ServiceEstimateResponse(_Response):
    service_name: str
    currency: str
    parts: list[EstimatedPartResponse]
    labour: LabourEstimateResponse
    estimated_duration_hours: float
    parts_cost: Decimal
    labour_cost: Decimal
    estimated_cost: Decimal

class ComplaintSummaryResponse(_Response):
    category: str
    description: str
    status: ComplaintCoverageStatus
    evidence: str
    confidence: float | None

class PostCallSummaryResponse(_Response):
    call_id: str
    overall_summary: str
    languages: list[str]
    sentiment: SentimentResponse
    complaints: list[ComplaintSummaryResponse]
    unresolved_issues: list[str]
    actions_promised: list[str]
    follow_up_required: bool
    customer_summary: str
    service_estimate: ServiceEstimateResponse | None

class CallAnalysisResponse(_Response):
    call_id: str
    coverage: CoverageResponse
    sentiment: SentimentResponse | None
    question_suggestion: QuestionSuggestionResponse | None
    service_estimate: ServiceEstimateResponse | None = None
    post_call_summary: PostCallSummaryResponse | None = None
    # null while the call has not escalated
    escalation: "EscalationResponse | None" = None


class EscalationSignalResponse(_Response):
    signal_type: EscalationSignalType
    level: EscalationLevel
    description: str
    evidence: str | None


class EscalationResponse(_Response):
    call_id: str
    level: EscalationLevel
    status: EscalationStatus
    signals: list[EscalationSignalResponse]
    first_detected_at: float
    updated_at: float
    acknowledged_by: str | None
    acknowledged_at: float | None
    resolved_by: str | None
    resolved_at: float | None
    resolution_note: str | None


class EscalationStatsResponse(_Response):
    active: int
    critical: int
    unacknowledged: int


class ResolveEscalationRequest(_Request):
    note: str | None = Field(default=None, max_length=500)


CallAnalysisResponse.model_rebuild()