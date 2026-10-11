import logging
import time
from collections.abc import Callable

from app.ai.llm.call_context import current_call_id
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.services.ai_log import AiLog, AiOutcome

logger = logging.getLogger(__name__)


class LoggedLLMClient(LLMClient):
    """Passes every request to the real client and puts it in the AI log:
    the call being worked on, the task, the prompt, the answer (or the
    failure) and how long it took. Keeping the log never fails a request."""

    def __init__(
        self,
        inner: LLMClient,
        log: AiLog,
        model: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._inner = inner
        self._log = log
        self._model = model
        self._clock = clock

    def complete(self, request: LLMRequest) -> LLMResponse:
        started_at = self._clock()
        started = time.monotonic()
        try:
            response = self._inner.complete(request)
        except Exception as exc:
            self._record(request, None, started_at, started, AiOutcome.FAILED, str(exc))
            raise
        response.log_id = self._record(
            request, response, started_at, started, AiOutcome.ANSWERED, None
        )
        return response

    def report_unusable(self, response: LLMResponse, reason: str) -> None:
        if response.log_id is None:
            return
        try:
            self._log.mark_unusable(response.log_id, reason)
        except Exception:
            logger.exception("Could not mark an AI log entry as unusable")

    def _record(
        self,
        request: LLMRequest,
        response: LLMResponse | None,
        started_at: float,
        started: float,
        outcome: AiOutcome,
        note: str | None,
    ) -> str | None:
        try:
            return self._log.record(
                call_id=current_call_id(),
                task=request.task,
                model=(response.model if response is not None else "") or self._model,
                prompt=request.prompt,
                answer=None if response is None else response.text,
                started_at=started_at,
                duration_ms=round((time.monotonic() - started) * 1000, 1),
                outcome=outcome,
                attempt=request.attempt,
                prompt_tokens=None if response is None else response.prompt_tokens,
                completion_tokens=None if response is None else response.completion_tokens,
                note=note,
            )
        except Exception:
            logger.exception("Could not add a request to the AI log")
            return None
