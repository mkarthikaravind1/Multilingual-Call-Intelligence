from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from app.ai.sentiment.provider import SentimentLabel
from app.domain.complaint_coverage import ComplaintCoverageStatus
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
    sentiment: SentimentResponse
    question_suggestion: QuestionSuggestionResponse | None
    service_estimate: ServiceEstimateResponse | None = None
    post_call_summary: PostCallSummaryResponse | None = None