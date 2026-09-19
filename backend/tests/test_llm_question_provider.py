from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.llm_provider import LLMQuestionProvider
from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.question_suggestion import SuggestionSource


class FakeLLMClient(LLMClient):
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.received_request: LLMRequest | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.received_request = request
        return LLMResponse(text=self.response_text)


VALID_JSON = (
    '{"question": "What was the delay?", "target_category": "Turnaround Time", '
    '"priority": 2, "reason": "needs follow-up", "confidence": 0.8}'
)


def _context() -> QuestionGenerationContext:
    return QuestionGenerationContext(
        category="Turnaround Time",
        status=ComplaintCoverageStatus.DETECTED,
        utterances=(),
    )


def test_llm_provider_implements_question_suggestion_provider():
    assert issubclass(LLMQuestionProvider, QuestionSuggestionProvider)


def test_provider_accepts_injected_fake_client():
    client = FakeLLMClient(VALID_JSON)
    provider = LLMQuestionProvider(client)
    assert provider is not None


def test_context_is_converted_into_llm_request():
    client = FakeLLMClient(VALID_JSON)
    provider = LLMQuestionProvider(client)

    provider.generate(_context())

    assert client.received_request is not None
    assert "Turnaround Time" in client.received_request.prompt
    assert "detected" in client.received_request.prompt


def test_llm_client_is_called():
    client = FakeLLMClient(VALID_JSON)
    provider = LLMQuestionProvider(client)

    provider.generate(_context())

    assert client.received_request is not None


def test_valid_response_becomes_question_suggestion():
    client = FakeLLMClient(VALID_JSON)
    provider = LLMQuestionProvider(client)

    suggestion = provider.generate(_context())

    assert suggestion is not None
    assert suggestion.question == "What was the delay?"


def test_source_is_llm():
    client = FakeLLMClient(VALID_JSON)
    provider = LLMQuestionProvider(client)

    suggestion = provider.generate(_context())

    assert suggestion.source == SuggestionSource.LLM # type: ignore


def test_category_is_preserved():
    client = FakeLLMClient(VALID_JSON)
    provider = LLMQuestionProvider(client)

    suggestion = provider.generate(_context())

    assert suggestion.target_category == "Turnaround Time" # type: ignore


def test_invalid_json_is_rejected_safely():
    client = FakeLLMClient("not valid json")
    provider = LLMQuestionProvider(client)

    suggestion = provider.generate(_context())

    assert suggestion is None


def test_missing_required_field_is_rejected_safely():
    client = FakeLLMClient('{"question": "only this field"}')
    provider = LLMQuestionProvider(client)

    suggestion = provider.generate(_context())

    assert suggestion is None


def test_invalid_confidence_is_rejected_safely():
    bad_json = (
        '{"question": "q", "target_category": "Turnaround Time", '
        '"priority": 1, "reason": "r", "confidence": 5.0}'
    )
    client = FakeLLMClient(bad_json)
    provider = LLMQuestionProvider(client)

    suggestion = provider.generate(_context())

    assert suggestion is None