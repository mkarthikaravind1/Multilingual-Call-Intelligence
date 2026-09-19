from groq import Groq
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.core.config import settings

class GroqClientError(Exception):
    pass

class GroqLLMClient(LLMClient):
    def __init__(self, model: str | None = None) -> None:
        self._client = Groq(api_key=settings.groq_api_key)
        self._model = model or settings.groq_model

    def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": request.prompt}],
            )
        except Exception as exc:
            raise GroqClientError(f"Groq API call failed: {exc}") from exc

        text = response.choices[0].message.content or ""
        return LLMResponse(text=text)