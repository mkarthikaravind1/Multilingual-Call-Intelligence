from app.api.v1.schemas import (
    CallAnalysisResponse,
    CallListResponse,
    CallResponse,
    CallStatsResponse,
    CallSummaryResponse,
    CoverageResponse,
    PostCallSummaryResponse,
    QuestionSuggestionResponse,
    SentimentResponse,
    ServiceEstimateResponse,
    UtteranceRequest,
)
from app.domain.conversation import Conversation, ConversationStatus
from app.domain.utterance import Utterance
from app.services.call_workflow_service import CallAnalysisResult

def to_utterance(payload: UtteranceRequest) -> Utterance:
    return Utterance(
        utterance_id=payload.utterance_id,
        transcript=payload.transcript,
        speaker_role=payload.speaker_role,
        languages=tuple(payload.languages),
        start_time=payload.start_time,
        end_time=payload.end_time,
        confidence=payload.confidence,
    )

def to_call_response(conversation: Conversation) -> CallResponse:
    return CallResponse.model_validate(conversation)

def to_call_list_response(
    conversations: tuple[Conversation, ...], total: int, limit: int, offset: int
) -> CallListResponse:
    return CallListResponse(
        items=[CallSummaryResponse.model_validate(c) for c in conversations],
        total=total,
        limit=limit,
        offset=offset,
    )

def to_call_stats_response(counts: dict[ConversationStatus, int]) -> CallStatsResponse:
    active = counts.get(ConversationStatus.ACTIVE, 0)
    completed = counts.get(ConversationStatus.COMPLETED, 0)
    return CallStatsResponse(total=sum(counts.values()), active=active, completed=completed)

def to_analysis_response(
    call_id: str, result: CallAnalysisResult
) -> CallAnalysisResponse:
    suggestion = result.question_suggestion
    estimate = result.service_estimate
    summary = result.post_call_summary
    return CallAnalysisResponse(
        call_id=call_id,
        coverage=CoverageResponse.model_validate(result.coverage),
        sentiment=(
            SentimentResponse.model_validate(result.sentiment)
            if result.sentiment is not None
            else None
        ),
        question_suggestion=(
            QuestionSuggestionResponse.model_validate(suggestion)
            if suggestion is not None
            else None
        ),
        service_estimate=(
            ServiceEstimateResponse.model_validate(estimate)
            if estimate is not None
            else None
        ),
        post_call_summary=(
            PostCallSummaryResponse.model_validate(summary)
            if summary is not None
            else None
        ),
    )