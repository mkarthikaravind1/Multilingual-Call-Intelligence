from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class LLMRequest:
    prompt: str
    # What the request is for ("complaints", "sentiment", ...): the name it
    # is kept under in the AI log.
    task: str = ""
    # 2 when this asks again for an answer that could not be used.
    attempt: int = 1

@dataclass
class LLMResponse:
    text: str
    model: str = ""
    # As the provider counted them; None when it did not say.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # This answer's entry in the AI log, when one is kept.
    log_id: str | None = None

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

    def report_unusable(self, response: LLMResponse, reason: str) -> None:
        """Told by the caller that it could not use this answer (it is not
        the JSON asked for, say). Only a client that keeps a log cares."""
