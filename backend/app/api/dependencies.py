from dataclasses import dataclass, field
from fastapi import Request
from app.composition.learning import build_learning_management_service
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.learning_management_service import LearningManagementService
from starlette.requests import HTTPConnection
from app.api.v1.live_handler import LiveCallHandler
from app.services.auth_service import AuthService
from app.domain.user_repository import UserRepository
from app.domain.user_repository import InMemoryUserRepository

@dataclass(frozen=True)
class ApiServices:
    call_service: CallService
    workflow_service: CallWorkflowService
    learning: LearningManagementService = field(
        default_factory=build_learning_management_service
    )
    auth: AuthService = field(default_factory=lambda: AuthService(InMemoryUserRepository()))
    user_repository: UserRepository = field(default_factory=InMemoryUserRepository)

def get_call_service(request: Request) -> CallService:
    return request.app.state.services.call_service

def get_workflow_service(request: Request) -> CallWorkflowService:
    return request.app.state.services.workflow_service

def get_learning_service(request: Request) -> LearningManagementService:
    return request.app.state.services.learning

def get_live_call_handler(connection: HTTPConnection) -> LiveCallHandler:
    services = connection.app.state.services
    return LiveCallHandler(services.call_service, services.workflow_service)

def get_auth_service(request: Request) -> AuthService:
    return request.app.state.services.auth

def get_user_repository(request: Request) -> UserRepository:
    return request.app.state.services.user_repository