from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_call_service, get_workflow_service
from app.api.v1.mappers import to_analysis_response, to_call_response, to_utterance
from app.api.v1.schemas import (
    CallAnalysisResponse,
    CallResponse,
    CompleteCallRequest,
    StartCallRequest,
    UtteranceRequest,
)
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
router = APIRouter(prefix="/calls", tags=["calls"])

@router.post("", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
def start_call(
    payload: StartCallRequest,
    call_service: CallService = Depends(get_call_service),
) -> CallResponse:
    return to_call_response(call_service.start_call(payload.call_id, payload.start_time))

@router.get("/{call_id}", response_model=CallResponse)
def get_call(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
) -> CallResponse:
    return to_call_response(call_service.get_call(call_id))

@router.post("/{call_id}/utterances", response_model=CallAnalysisResponse)
def add_utterance(
    call_id: str,
    payload: UtteranceRequest,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
) -> CallAnalysisResponse:
    result = workflow_service.process_utterance(call_id, to_utterance(payload))
    return to_analysis_response(call_id, result)

@router.get("/{call_id}/analysis", response_model=CallAnalysisResponse)
def get_analysis(
    call_id: str,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
) -> CallAnalysisResponse:
    return to_analysis_response(call_id, workflow_service.analyze_call(call_id))

@router.post("/{call_id}/complete", response_model=CallResponse)
def complete_call(
    call_id: str,
    payload: CompleteCallRequest,
    call_service: CallService = Depends(get_call_service),
) -> CallResponse:
    return to_call_response(call_service.end_call(call_id, payload.end_time))