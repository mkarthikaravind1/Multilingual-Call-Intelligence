from dataclasses import dataclass
from fastapi import Request
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from starlette.requests import HTTPConnection
from app.api.v1.live_handler import LiveCallHandler

@dataclass(frozen=True)
class ApiServices:
    call_service: CallService
    workflow_service: CallWorkflowService

def get_call_service(request: Request) -> CallService:
    return request.app.state.services.call_service

def get_workflow_service(request: Request) -> CallWorkflowService:
    return request.app.state.services.workflow_service

def get_live_call_handler(connection: HTTPConnection) -> LiveCallHandler:
    services = connection.app.state.services
    return LiveCallHandler(services.call_service, services.workflow_service)