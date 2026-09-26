from dataclasses import dataclass

from fastapi import Request
from starlette.requests import HTTPConnection

from app.api.v1.live_handler import LiveCallHandler
from app.domain.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.learning_management_service import LearningManagementService
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.provider import TelephonyProvider


@dataclass(frozen=True)
class ApiServices:
    call_service: CallService
    workflow_service: CallWorkflowService

    learning: LearningManagementService | None = None
    auth: AuthService | None = None
    user_repository: UserRepository | None = None

    telephony_provider: TelephonyProvider | None = None
    telephony_call_service: TelephonyCallService | None = None


def get_call_service(request: Request) -> CallService:
    return request.app.state.services.call_service


def get_workflow_service(request: Request) -> CallWorkflowService:
    return request.app.state.services.workflow_service


def get_learning_service(request: Request) -> LearningManagementService:
    return request.app.state.services.learning


def get_live_call_handler(connection: HTTPConnection) -> LiveCallHandler:
    services = connection.app.state.services
    return LiveCallHandler(
        services.call_service,
        services.workflow_service,
    )


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.services.auth


def get_user_repository(request: Request) -> UserRepository:
    return request.app.state.services.user_repository


def get_telephony_provider(
    request: Request,
) -> TelephonyProvider | None:
    return request.app.state.services.telephony_provider


def get_telephony_call_service(
    request: Request,
) -> TelephonyCallService:
    return request.app.state.services.telephony_call_service