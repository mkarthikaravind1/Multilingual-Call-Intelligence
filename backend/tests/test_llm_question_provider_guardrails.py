import json
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.llm_provider import LLMQuestionProvider
from app.ai.question.provider import QuestionGenerationContext
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance

VALID = {
    "question": "When did the higher Cost amount first appear?",
    "target_category": "Cost",
    "priority": 1,
    "reason": "The customer mentioned the bill but not when it changed.",
    "confidence": 0.8,
}


def _context(utterances=("The final bill was much higher than the estimate.",)):
    return QuestionGenerationContext(
        category="Cost",
        status=ComplaintCoverageStatus.DETECTED,
        utterances=tuple(
            Utterance(
                utterance_id="1",
                transcript=text,
                speaker_role=SpeakerRole.CUSTOMER,
                languages=("en",),
                start_time=float(i),
                end_time=float(i) + 1.0,
            )
            for i, text in enumerate(utterances)
        ),
    )


def _provider(text):
    client = create_autospec(LLMClient, instance=True)
    client.complete.return_value = LLMResponse(text=text)
    return LLMQuestionProvider(client), client


def _payload(**overrides):
    return json.dumps({**VALID, **overrides})


def _without(key):
    return json.dumps({k: v for k, v in VALID.items() if k != key})


def test_valid_response_becomes_question_suggestion():
    provider, _ = _provider(_payload())

    result = provider.generate(_context())

    assert isinstance(result, QuestionSuggestion)
    assert result.question == VALID["question"]
    assert result.target_category == "Cost"
    assert result.priority == 1
    assert result.reason == VALID["reason"]
    assert result.confidence == 0.8
    assert result.source == SuggestionSource.LLM


def test_json_wrapped_in_code_fence_is_accepted():
    provider, _ = _provider(f"```json\n{_payload()}\n```")

    assert provider.generate(_context()) is not None


def test_missing_confidence_is_allowed():
    provider, _ = _provider(_without("confidence"))

    result = provider.generate(_context())

    assert result is not None
    assert result.confidence is None


def test_explicit_null_from_model_returns_none():
    provider, _ = _provider("null")

    assert provider.generate(_context()) is None


INVALID_RESPONSES = [
    pytest.param("not json at all", id="invalid-json"),
    pytest.param("", id="empty-response"),
    pytest.param('{"question": "abc', id="truncated-json"),
    pytest.param("[]", id="json-array"),
    pytest.param('"just text"', id="json-string"),
    pytest.param("42", id="json-number"),
    pytest.param(_without("question"), id="missing-question"),
    pytest.param(_without("target_category"), id="missing-category"),
    pytest.param(_without("priority"), id="missing-priority"),
    pytest.param(_without("reason"), id="missing-reason"),
    pytest.param(_payload(question=123), id="question-wrong-type"),
    pytest.param(_payload(reason=["x"]), id="reason-wrong-type"),
    pytest.param(_payload(target_category=5), id="category-wrong-type"),
    pytest.param(_payload(priority="high"), id="priority-string"),
    pytest.param(_payload(priority=1.5), id="priority-float"),
    pytest.param(_payload(priority=True), id="priority-bool"),
    pytest.param(_payload(confidence="high"), id="confidence-string"),
    pytest.param(_payload(confidence=True), id="confidence-bool"),
    pytest.param(_payload(target_category="Banana"), id="unsupported-category"),
    pytest.param(_payload(target_category="Hygiene"), id="unrelated-category"),
    pytest.param(_payload(question=""), id="empty-question"),
    pytest.param(_payload(question="   "), id="blank-question"),
    pytest.param(_payload(reason=""), id="empty-reason"),
    pytest.param(_payload(reason="   "), id="blank-reason"),
]


@pytest.mark.parametrize("text", INVALID_RESPONSES)
def test_invalid_model_output_returns_none(text):
    provider, _ = _provider(text)

    assert provider.generate(_context()) is None


@pytest.mark.parametrize(
    "overrides",
    [{"priority": -1}, {"confidence": 1.5}, {"confidence": -0.1}],
    ids=["negative-priority", "confidence-above-1", "confidence-below-0"],
)
def test_out_of_range_values_rejected_by_domain_validation(overrides):
    provider, _ = _provider(_payload(**overrides))

    assert provider.generate(_context()) is None


def test_non_string_response_text_returns_none():
    client = create_autospec(LLMClient, instance=True)
    client.complete.return_value = SimpleNamespace(text=None)

    assert LLMQuestionProvider(client).generate(_context()) is None


def test_empty_conversation_still_sends_request_with_placeholder():
    provider, client = _provider("null")

    assert provider.generate(_context(utterances=())) is None

    client.complete.assert_called_once()
    assert "no conversation available yet" in client.complete.call_args.args[0].prompt


def test_prompt_contains_context_guardrails_and_json_contract():
    provider, client = _provider(_payload())

    provider.generate(_context(("The final bill was much higher.",)))

    client.complete.assert_called_once()
    request = client.complete.call_args.args[0]
    assert isinstance(request, LLMRequest)
    prompt = request.prompt
    assert "Target complaint category: Cost" in prompt
    assert "Current complaint status: detected" in prompt
    assert "The final bill was much higher." in prompt
    assert "ONLY a single JSON object" in prompt
    for key in ("question", "target_category", "priority", "reason", "confidence"):
        assert f'"{key}"' in prompt
    assert "Do not invent facts" in prompt
    assert "Do not ask about any other complaint category" in prompt
    assert "exactly: null" in prompt