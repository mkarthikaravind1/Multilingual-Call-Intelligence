from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class LLMRequest:
    prompt: str

@dataclass
class LLMResponse:
    text: str

class LLMRateLimitedError(Exception):
    """The LLM provider refused the request for now (a rate limit).
    retry_after_seconds: how long it asked to wait, when it said."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def rate_limit_in(exc: BaseException | None) -> LLMRateLimitedError | None:
    """The LLMRateLimitedError among exc and the exceptions that caused it."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, LLMRateLimitedError):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


class LLMClient(ABC):
    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError