import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import cast,Any

import pytest

from app.ai.complaint import llm_provider as llm_provider_module
from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.conversation import Conversation
from app.domain.utterance import SpeakerRole, Utterance

DEFAULT_LINES = (
    (SpeakerRole.CUSTOMER, "The vehicle was delivered two days late."),
    (SpeakerRole.CUSTOMER, "Nobody informed me about the delay."),
)


class FakeLLMClient(LLMClient):
    def __init__(
        self, response_text: str = "[]", error: Exception | None = None
    ) -> None:
        self.response_text = response_text
        self.error = error
        self.received_request: LLMRequest | None = None
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        self.received_request = request
        if self.error is not None:
            raise self.error
        return LLMResponse(text=self.response_text)


def _conversation(lines=DEFAULT_LINES) -> Conversation:
    utterances = tuple(
        Utterance(
            utterance_id="1",
            transcript=text,
            speaker_role=role,
            languages=("en",),
            start_time=float(i),
            end_time=float(i) + 1.0,
        )
        for i, (role, text) in enumerate(lines)
    )
    return cast(Conversation, SimpleNamespace(utterances=utterances))


def _item(
    category: Any = "Turnaround Time",
    confidence: Any = 0.93,
    evidence: Any = "The customer said the vehicle was delivered two days late.",
) -> dict[str, Any]:
    return {"category": category, "confidence": confidence, "evidence": evidence}


def _item_without(key):
    return {k: v for k, v in _item().items() if k != key}


def _response(*items) -> str:
    return json.dumps(list(items))


def _detect(response_text: str) -> list[ComplaintDetectionResult]:
    return LLMComplaintProvider(FakeLLMClient(response_text)).detect(_conversation())


def test_llm_provider_implements_complaint_detection_provider():
    assert issubclass(LLMComplaintProvider, ComplaintDetectionProvider)


def test_one_valid_complaint():
    results = _detect(_response(_item()))

    assert len(results) == 1
    assert isinstance(results[0], ComplaintDetectionResult)
    assert results[0].category == "Turnaround Time"
    assert results[0].confidence == 0.93
    assert results[0].evidence == (
        "The customer said the vehicle was delivered two days late."
    )


def test_multiple_valid_complaints_are_returned_in_order():
    results = _detect(
        _response(
            _item(),
            _item(
                "Communication",
                0.87,
                "The customer said nobody informed them about the delay.",
            ),
        )
    )

    assert [r.category for r in results] == ["Turnaround Time", "Communication"]
    assert [r.confidence for r in results] == [0.93, 0.87]


def test_empty_complaint_list_returns_empty_list():
    assert _detect("[]") == []


def test_json_wrapped_in_code_fence_is_accepted():
    results = _detect(f"```json\n{_response(_item())}\n```")

    assert len(results) == 1


def test_evidence_is_stripped():
    results = _detect(_response(_item(evidence="  late delivery  ")))

    assert results[0].evidence == "late delivery"


INVALID_RESPONSES = [
    pytest.param("not json at all", id="invalid-json"),
    pytest.param("", id="empty-response"),
    pytest.param('[{"category": "Cost"', id="truncated-json"),
    pytest.param(json.dumps(_item()), id="object-instead-of-list"),
    pytest.param("null", id="json-null"),
    pytest.param('"just text"', id="json-string"),
    pytest.param("42", id="json-number"),
    pytest.param('["Cost"]', id="item-is-string"),
    pytest.param("[1]", id="item-is-number"),
    pytest.param("[null]", id="item-is-null"),
    pytest.param(_response(_item_without("category")), id="missing-category"),
    pytest.param(_response(_item_without("confidence")), id="missing-confidence"),
    pytest.param(_response(_item_without("evidence")), id="missing-evidence"),
    pytest.param(_response(_item(category="Banana")), id="unsupported-category"),
    pytest.param(_response(_item(category="cost")), id="category-wrong-case"),
    pytest.param(_response(_item(category="5")), id="category-wrong-type"),
    pytest.param(_response(_item(confidence="high")), id="confidence-text"),
    pytest.param(_response(_item(confidence="0.9")), id="confidence-numeric-string"),
    pytest.param(_response(_item(confidence=None)), id="confidence-null"),
    pytest.param(_response(_item(confidence=True)), id="confidence-bool-true"),
    pytest.param(_response(_item(confidence=False)), id="confidence-bool-false"),
    pytest.param(_response(_item(confidence=1.5)), id="confidence-above-1"),
    pytest.param(_response(_item(confidence=-0.1)), id="confidence-below-0"),
    pytest.param(_response(_item(evidence="")), id="empty-evidence"),
    pytest.param(_response(_item(evidence="   ")), id="blank-evidence"),
    pytest.param(_response(_item(evidence=123)), id="evidence-wrong-type"),
    pytest.param(_response(_item(evidence=None)), id="evidence-null"),
    pytest.param(_response(_item("Cost"), _item("Cost")), id="duplicate-categories"),
    pytest.param(
        _response(_item("Cost"), _item("Communication"), _item("Cost", 0.5)),
        id="duplicate-among-valid-items",
    ),
    pytest.param(
        _response(_item("Cost"), _item("Communication", 2.0)),
        id="one-invalid-item-rejects-whole-response",
    ),
    pytest.param(
        _response(_item("Cost"), _item(category="Banana")),
        id="unsupported-category-is-not-converted-to-other",
    ),
]


@pytest.mark.parametrize("response_text", INVALID_RESPONSES)
def test_invalid_model_output_returns_empty_list(response_text):
    assert _detect(response_text) == []


def test_non_string_response_text_returns_empty_list():
    client = FakeLLMClient(response_text=None)  # type: ignore

    assert LLMComplaintProvider(client).detect(_conversation()) == []


def test_invalid_response_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        _detect(_response(_item("Cost"), _item("Cost")))

    assert "duplicate categories" in caplog.text


def test_llm_client_failure_propagates():
    client = FakeLLMClient(error=RuntimeError("LLM unavailable"))

    with pytest.raises(RuntimeError, match="LLM unavailable"):
        LLMComplaintProvider(client).detect(_conversation())


def test_conversation_without_utterances_skips_llm_call():
    client = FakeLLMClient(_response(_item()))

    results = LLMComplaintProvider(client).detect(_conversation(lines=()))

    assert results == []
    assert client.call_count == 0


def test_prompt_contains_categories_transcript_guardrails_and_json_contract():
    client = FakeLLMClient("[]")

    LLMComplaintProvider(client).detect(_conversation())

    assert client.call_count == 1
    assert client.received_request is not None
    prompt = client.received_request.prompt
    for category in COMPLAINT_CATEGORIES:
        assert f"- {category}" in prompt
    assert "CUSTOMER: The vehicle was delivered two days late." in prompt
    assert "CUSTOMER: Nobody informed me about the delay." in prompt
    assert "do not invent complaints" in prompt
    assert "Report every category" in prompt
    assert "Report each category at most once" in prompt
    assert "ONLY a JSON array" in prompt
    for key in ("category", "confidence", "evidence"):
        assert f'"{key}"' in prompt
    assert "exactly: []" in prompt


def test_llm_complaint_provider_does_not_import_groq():
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