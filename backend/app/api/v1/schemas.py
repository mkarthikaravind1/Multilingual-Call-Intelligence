from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from app.ai.sentiment.provider import SentimentLabel
from app.domain.call_alert import CallAlertType, QuestionOutcomeChoice
from app.domain.call_customer import CustomerMatchStatus
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.customer_contact import ConsentStatus, MessagingChannel
from app.domain.customer_summary_delivery import DeliveryStatus
from app.domain.escalation import EscalationLevel, EscalationSignalType, EscalationStatus
from app.domain.conversation import CallDirection, CallPhase, ConversationStatus
from app.domain.question_suggestion import SuggestionSource
from app.domain.utterance import SpeakerRole
from app.services.call_indicators import AiStatus, LoggingStatus

class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class StartCallRequest(_Request):
    call_id: str = Field(min_length=1)
    # null: now, by the server's clock. The web app sends null: a PC's
    # clock can be minutes off, and phone calls start on the server's.
    start_time: float | None = 0.0
    # Optional: the customer's number when it is known up front.
    caller_number: str | None = Field(default=None, min_length=1, max_length=32)
    # Whether the customer called (the default) or was called.
    direction: CallDirection = CallDirection.INBOUND


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
    # Left out (or null): now, by the server's clock.
    end_time: float | None = None

class UtteranceResponse(_Response):
    utterance_id: str
    transcript: str
    speaker_role: SpeakerRole
    languages: list[str]
    start_time: float
    end_time: float
    confidence: float | None
    # The speaker's tone on this line; null until the analysis has rated
    # it (customer lines only).
    sentiment: SentimentLabel | None = None
    sentiment_confidence: float | None = None
    # The complaint categories this line raises, once the analysis has
    # found them; multi_category: it covers more than one.
    complaint_categories: list[str] = []
    multi_category: bool = False

class HoldPeriodResponse(_Response):
    started_at: float
    # null while the hold is on.
    ended_at: float | None = None


class HoldRequest(_Request):
    # Left out (or null): now, by the server's clock.
    at: float | None = None


class CallResponse(_Response):
    call_id: str
    status: ConversationStatus
    start_time: float
    end_time: float | None
    utterance_count: int
    utterances: list[UtteranceResponse]
    # null: not recorded for this call.
    direction: CallDirection | None = None
    location_id: str | None = None
    executive_user_id: str | None = None
    # Where the call stands: incoming or outgoing (ringing), connected,
    # on_hold or ended.
    phase: CallPhase = CallPhase.CONNECTED
    # Each time it was put on hold, oldest first, and the time spent in
    # holds that have ended.
    holds: list[HoldPeriodResponse] = []
    hold_seconds: float = 0.0

class CallSummaryResponse(_Response):
    call_id: str
    status: ConversationStatus
    # See CallResponse.phase.
    phase: CallPhase = CallPhase.CONNECTED
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
    # Where the call was taken and by whom; null when not recorded.
    direction: CallDirection | None = None
    location_id: str | None = None
    location_name: str | None = None
    executive_user_id: str | None = None
    executive_name: str | None = None


class CallDirectoryEntry(BaseModel):
    id: str
    name: str
    is_active: bool


class CallDirectoryResponse(BaseModel):
    """What calls can be filtered by: the locations and the executives."""

    locations: list[CallDirectoryEntry]
    executives: list[CallDirectoryEntry]


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
    # How sure the detector was (0 to 1); null when not recorded.
    confidence: float | None = None


class CallAlertResponse(_Response):
    alert_type: CallAlertType
    # The complaint category the alert is about; "" for the call itself.
    subject: str
    message: str
    raised_at: float
    # null while the alert stands.
    cleared_at: float | None


class QuestionOutcomeRequest(_Request):
    question: str = Field(min_length=1, max_length=2000)
    target_category: str = Field(min_length=1, max_length=100)
    outcome: QuestionOutcomeChoice


class QuestionOutcomeResponse(_Response):
    question: str
    target_category: str
    outcome: QuestionOutcomeChoice
    created_at: float


class LiveCallResponse(BaseModel):
    """An active call, as the supervisor's live view shows it."""

    call_id: str
    # See CallResponse.phase.
    phase: CallPhase = CallPhase.CONNECTED
    start_time: float
    direction: CallDirection | None
    location_name: str | None
    executive_name: str | None
    caller_number: str | None
    customer_name: str | None
    utterance_count: int
    # The customer's tone at the latest analysis; null before the first.
    sentiment: SentimentLabel | None
    complaints: list[ComplaintCoverageResponse]
    escalation_level: EscalationLevel | None
    escalation_status: EscalationStatus | None
    # Standing alerts only.
    alerts: list[CallAlertResponse]


class LiveCallsResponse(BaseModel):
    # One page of the calls matching the filters, most urgent first.
    items: list[LiveCallResponse]
    limit: int
    offset: int
    # Calls matching the filters, across all pages.
    matching: int
    # Over every call in progress, whatever the filters:
    total: int
    with_alerts: int
    negative_tone: int
    escalated: int
    # The server's clock (epoch seconds), for showing durations.
    now: float

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
    # The question is in the customer's language; question_en is its
    # English version (None when the question is already in English).
    language: str = "en"
    question_en: str | None = None

class EstimatedPartResponse(_Response):
    name: str
    quantity: int
    # Before GST.
    unit_price: Decimal
    total_price: Decimal
    gst_percent: Decimal
    gst_amount: Decimal

class LabourEstimateResponse(_Response):
    hours: float
    # Before GST.
    hourly_rate: Decimal
    total_cost: Decimal
    gst_percent: Decimal
    gst_amount: Decimal

class ServiceLineResponse(_Response):
    """One service of the estimate, priced from the price list."""
    service_name: str
    currency: str
    parts: list[EstimatedPartResponse]
    labour: LabourEstimateResponse
    estimated_duration_hours: float
    parts_cost: Decimal
    labour_cost: Decimal
    # Before GST; total_cost = estimated_cost + gst_amount.
    estimated_cost: Decimal
    gst_amount: Decimal
    total_cost: Decimal
    # The vehicle model this price is for; None: the all-models price.
    priced_for_model: str | None = None
    # The service is priced per model, but not for this vehicle.
    approximate: bool = False

class ServiceEstimateResponse(_Response):
    """Every service that came up in the call, and their totals."""
    currency: str
    services: list[ServiceLineResponse]
    estimated_duration_hours: float
    parts_cost: Decimal
    labour_cost: Decimal
    # Before GST; total_cost = estimated_cost + gst_amount.
    estimated_cost: Decimal
    gst_amount: Decimal
    total_cost: Decimal
    vehicle_model: str | None = None
    approximate: bool = False

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
    # The most relevant suggested question (the first of
    # question_suggestions).
    question_suggestion: QuestionSuggestionResponse | None
    # Every suggested question, the most relevant first.
    question_suggestions: list[QuestionSuggestionResponse] = []
    # What the AI is doing with the call right now; null once it has ended
    # or while it is on hold.
    ai_status: AiStatus | None = None
    # Where the call's record stands: recording while it is kept as it is
    # spoken; archive_complete and export_ready once each holds.
    logging_statuses: list[LoggingStatus] = []
    service_estimate: ServiceEstimateResponse | None = None
    post_call_summary: PostCallSummaryResponse | None = None
    # null while the call has not escalated
    escalation: "EscalationResponse | None" = None
    # The call's alerts, standing and cleared, oldest first.
    alerts: list[CallAlertResponse] = []


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