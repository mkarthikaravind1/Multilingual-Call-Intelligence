from abc import ABC, abstractmethod

from app.domain.telephony_call_mapping import TelephonyCallMapping


class TelephonyCallMappingRepository(ABC):
    @abstractmethod
    def save(self, mapping: TelephonyCallMapping) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_provider_call_id(self, provider_call_id: str) -> TelephonyCallMapping | None:
        raise NotImplementedError


class InMemoryTelephonyCallMappingRepository(TelephonyCallMappingRepository):
    def __init__(self) -> None:
        self._by_provider_call_id: dict[str, TelephonyCallMapping] = {}

    def save(self, mapping: TelephonyCallMapping) -> None:
        self._by_provider_call_id[mapping.provider_call_id] = mapping

    def get_by_provider_call_id(self, provider_call_id: str) -> TelephonyCallMapping | None:
        return self._by_provider_call_id.get(provider_call_id)