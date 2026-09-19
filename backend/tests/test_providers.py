import ast
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from app.ai.llm.client import LLMClient
from app.ai.question import llm_provider as llm_provider_module
from app.ai.question.llm_provider import LLMQuestionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.composition import providers
from app.composition.providers import (
    UnsupportedProviderError,
    create_llm_client,
    create_question_provider,
)
from app.core.config import Settings
from types import SimpleNamespace

from app.ai.llm.client import LLMClient, LLMResponse


class FakeGroqLLMClient:
    def __init__(self, model: str | None = None) -> None:
        self.model = model


def _settings(provider: str) -> Settings:
    return Settings.model_construct(llm_provider=provider)


def test_create_llm_client_builds_groq_from_settings(monkeypatch):
    monkeypatch.setattr(providers, "GroqLLMClient", FakeGroqLLMClient)

    client = create_llm_client(_settings("GROQ"), model="test-model")

    assert isinstance(client, FakeGroqLLMClient)
    assert client.model == "test-model"


@pytest.mark.parametrize("name", ["not_configured", "unknown"])
def test_create_llm_client_rejects_unsupported_provider(name):
    with pytest.raises(UnsupportedProviderError, match=name):
        create_llm_client(_settings(name))


def test_question_provider_receives_injected_client(monkeypatch):
    captured = {}

    class RecordingProvider:
        def __init__(self, llm_client):
            captured["client"] = llm_client

    monkeypatch.setattr(providers, "LLMQuestionProvider", RecordingProvider)
    llm_client = create_autospec(LLMClient, instance=True)

    create_question_provider(llm_client=llm_client)

    assert captured["client"] is llm_client


def test_question_provider_is_abstract_provider_type():
    llm_client = create_autospec(LLMClient, instance=True)

    provider = create_question_provider(llm_client=llm_client)

    assert isinstance(provider, LLMQuestionProvider)
    assert isinstance(provider, QuestionSuggestionProvider)


def test_default_wiring_uses_groq_without_network(monkeypatch):
    monkeypatch.setattr(providers, "GroqLLMClient", FakeGroqLLMClient)

    provider = create_question_provider(settings=_settings("groq"))

    assert isinstance(provider, LLMQuestionProvider)


def test_llm_question_provider_does_not_import_groq():
    tree = ast.parse(Path(llm_provider_module.__file__).read_text())
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]

    assert not any("groq" in name.lower() for name in imported)

def test_wired_provider_calls_injected_client_and_returns_none_on_bad_json():
    llm_client = create_autospec(LLMClient, instance=True)
    llm_client.complete.return_value = LLMResponse(text="not json")
    provider = create_question_provider(llm_client=llm_client)
    context = SimpleNamespace(
        category="Cost",
        status=SimpleNamespace(value="detected"),
        utterances=[SimpleNamespace(transcript="The bill was too high")],
    )

    result = provider.generate(context) # type: ignore

    llm_client.complete.assert_called_once()
    assert "Cost" in llm_client.complete.call_args.args[0].prompt
    assert result is None