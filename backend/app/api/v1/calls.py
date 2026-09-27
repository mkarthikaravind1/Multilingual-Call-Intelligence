from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_call_service, get_workflow_service
from app.api.v1.mappers import (
    to_analysis_response,
    to_call_list_response,
    to_call_response,
    to_call_stats_response,
    to_utterance,
)
from app.api.v1.schemas import (
    CallAnalysisResponse,
    CallListResponse,
    CallResponse,
    CallStatsResponse,
    CompleteCallRequest,
    StartCallRequest,
    UtteranceRequest,
)
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.api.security_dependencies import get_current_user
from app.domain.user import User


router = APIRouter(prefix="/calls", tags=["calls"])
# Separate path so it can never collide with a call_id of "stats".
stats_router = APIRouter(tags=["calls"])

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

@router.get("", response_model=CallListResponse)
def list_calls(
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> CallListResponse:
    return to_call_list_response(
        call_service.list_calls(limit, offset),
        total=call_service.count_calls(),
        limit=limit,
        offset=offset,
    )

@stats_router.get("/call-stats", response_model=CallStatsResponse)
def get_call_stats(
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> CallStatsResponse:
    return to_call_stats_response(call_service.count_calls_by_status())

@router.post("", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
def start_call(
    payload: StartCallRequest,
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> CallResponse:
    return to_call_response(call_service.start_call(payload.call_id, payload.start_time))

@router.get("/{call_id}", response_model=CallResponse)
def get_call(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> CallResponse:
    return to_call_response(call_service.get_call(call_id))

@router.post("/{call_id}/utterances", response_model=CallAnalysisResponse)
def add_utterance(
    call_id: str,
    payload: UtteranceRequest,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(get_current_user),
) -> CallAnalysisResponse:
    result = workflow_service.process_utterance(call_id, to_utterance(payload))
    return to_analysis_response(call_id, result)

@router.get("/{call_id}/analysis", response_model=CallAnalysisResponse)
def get_analysis(
    call_id: str,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(get_current_user),
) -> CallAnalysisResponse:
    return to_analysis_response(call_id, workflow_service.analyze_call(call_id))

@router.post("/{call_id}/complete", response_model=CallResponse)
def complete_call(
    call_id: str,
    payload: CompleteCallRequest,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(get_current_user),
) -> CallResponse:
    completion = workflow_service.complete_call(call_id, payload.end_time)
    return to_call_response(completion.conversation)