from dataclasses import dataclass


@dataclass(frozen=True)
class TelephonyCallMapping:
    provider: str
    provider_call_id: str
    call_id: str
    created_at: float

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be empty.")
        if not self.provider_call_id.strip():
            raise ValueError("provider_call_id must not be empty.")
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")