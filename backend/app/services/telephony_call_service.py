import time
from uuid import uuid4

from app.domain.conversation import ConversationStatus
from app.domain.telephony_call_mapping import TelephonyCallMapping
from app.services.call_service import CallService
from app.services.telephony_call_mapping_repository import TelephonyCallMappingRepository
from app.telephony.provider import CallProviderStatus, CallStatusEvent, InboundCallEvent

_TERMINAL_STATUSES = frozenset(
    {
        CallProviderStatus.COMPLETED,
        CallProviderStatus.FAILED,
        CallProviderStatus.BUSY,
        CallProviderStatus.NO_ANSWER,
    }
)


class TelephonyCallService:
    def __init__(
        self,
        call_service: CallService,
        mapping_repository: TelephonyCallMappingRepository,
    ) -> None:
        self._call_service = call_service
        self._mapping_repository = mapping_repository

    def start_call_from_provider(self, provider: str, event: InboundCallEvent) -> str:
        call_id = f"{provider}-{uuid4()}"
        self._call_service.start_call(call_id)
        self._mapping_repository.save(
            TelephonyCallMapping(
                provider=provider,
                provider_call_id=event.provider_call_id,
                call_id=call_id,
                created_at=time.time(),
            )
        )
        return call_id

    def resolve_call_id(self, provider_call_id: str) -> str | None:
        mapping = self._mapping_repository.get_by_provider_call_id(provider_call_id)
        return mapping.call_id if mapping is not None else None

    def handle_status_event(self, event: CallStatusEvent) -> bool:
        call_id = self.resolve_call_id(event.provider_call_id)
        if call_id is None:
            return False

        if event.status not in _TERMINAL_STATUSES:
            return True

        conversation = self._call_service.get_call(call_id)
        if conversation.status == ConversationStatus.COMPLETED:
            return True

        end_time = conversation.start_time
        if event.duration_seconds is not None:
            end_time = conversation.start_time + event.duration_seconds
        self._call_service.end_call(call_id, max(end_time, conversation.start_time))
        return True