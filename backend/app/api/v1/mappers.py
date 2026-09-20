from app.api.v1.schemas import (
    CallAnalysisResponse,
    CallResponse,
    CoverageResponse,
    QuestionSuggestionResponse,
    SentimentResponse,
    UtteranceRequest,
)
from app.domain.conversation import Conversation
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

def to_analysis_response(
    call_id: str, result: CallAnalysisResult
) -> CallAnalysisResponse:
    suggestion = result.question_suggestion
    return CallAnalysisResponse(
        call_id=call_id,
        coverage=CoverageResponse.model_validate(result.coverage),
        sentiment=SentimentResponse.model_validate(result.sentiment),
        question_suggestion=(
            QuestionSuggestionResponse.model_validate(suggestion)
            if suggestion is not None
            else None
        ),
    )