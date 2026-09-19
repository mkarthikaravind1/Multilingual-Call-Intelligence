from unittest.mock import MagicMock, patch

import pytest

from app.ai.llm.client import LLMRequest
from app.ai.llm.groq_client import GroqClientError, GroqLLMClient


def _mock_groq_response(text: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = text
    return response


@patch("app.ai.llm.groq_client.Groq")
def test_client_can_be_constructed(mock_groq):
    client = GroqLLMClient(model="test-model")
    assert client is not None
    mock_groq.assert_called_once()


@patch("app.ai.llm.groq_client.Groq")
def test_request_is_converted_correctly(mock_groq):
    mock_instance = mock_groq.return_value
    mock_instance.chat.completions.create.return_value = _mock_groq_response("hello")

    client = GroqLLMClient(model="test-model")
    client.complete(LLMRequest(prompt="Say hello"))

    _, kwargs = mock_instance.chat.completions.create.call_args
    assert kwargs["model"] == "test-model"
    assert kwargs["messages"] == [{"role": "user", "content": "Say hello"}]


@patch("app.ai.llm.groq_client.Groq")
def test_successful_response_becomes_llm_response(mock_groq):
    mock_instance = mock_groq.return_value
    mock_instance.chat.completions.create.return_value = _mock_groq_response("the answer")

    client = GroqLLMClient(model="test-model")
    result = client.complete(LLMRequest(prompt="question"))

    assert result.text == "the answer"


@patch("app.ai.llm.groq_client.Groq")
def test_api_failure_is_handled(mock_groq):
    mock_instance = mock_groq.return_value
    mock_instance.chat.completions.create.side_effect = RuntimeError("network down")

    client = GroqLLMClient(model="test-model")

    with pytest.raises(GroqClientError):
        client.complete(LLMRequest(prompt="question"))


@patch("app.ai.llm.groq_client.Groq")
def test_no_real_network_call_is_made(mock_groq):
    mock_instance = mock_groq.return_value
    mock_instance.chat.completions.create.return_value = _mock_groq_response("ok")

    GroqLLMClient(model="test-model").complete(LLMRequest(prompt="x"))

    mock_groq.assert_called_once()
    mock_instance.chat.completions.create.assert_called_once()