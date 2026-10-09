import re
import time

from groq import Groq, RateLimitError
from app.ai.llm.client import LLMClient, LLMRateLimitedError, LLMRequest, LLMResponse
from app.core.config import settings
from app.observability.metrics import PROVIDER_ERRORS, PROVIDER_REQUEST_DURATION

class GroqClientError(Exception):
    pass


class GroqRateLimitedError(GroqClientError, LLMRateLimitedError):
    pass


# "Please try again in 1m27.696s" / "in 1.37s" / "in 450ms"
_TRY_AGAIN_IN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?")


def _retry_after(exc: RateLimitError) -> float | None:
    header = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        if header is not None:
            return float(header)
    except ValueError:
        pass
    match = _TRY_AGAIN_IN.search(str(exc))
    if match is None or not any(match.groups()):
        return None
    hours, minutes, seconds, millis = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000

class GroqLLMClient(LLMClient):
    def __init__(self, model: str | None = None, max_retries: int | None = None) -> None:
        retries = settings.groq_max_retries if max_retries is None else max_retries
        self._client = Groq(api_key=settings.groq_api_key, max_retries=retries)
        self._model = model or settings.groq_model
        effort = settings.groq_reasoning_effort.strip().lower()
        # Only GPT-OSS models accept a reasoning effort.
        self._extra = (
            {"reasoning_effort": effort} if effort and "gpt-oss" in self._model else {}
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": request.prompt}],
                **self._extra,
            )
        except RateLimitError as exc:
            PROVIDER_ERRORS.inc("llm")
            raise GroqRateLimitedError(
                f"Groq API call failed: {exc}", _retry_after(exc)
            ) from exc
        except Exception as exc:
            PROVIDER_ERRORS.inc("llm")
            raise GroqClientError(f"Groq API call failed: {exc}") from exc
        finally:
            PROVIDER_REQUEST_DURATION.observe(time.monotonic() - started, "llm")

        text = response.choices[0].message.content or ""
        return LLMResponse(text=text)