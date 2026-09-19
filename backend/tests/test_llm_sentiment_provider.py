import json
from typing import Any

import pytest

from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.domain.conversation import Conversation
from app.domain.utterance import SpeakerRole, Utterance


class FakeLLMClient(LLMClient):
    def __init__(self, text: Any) -> None:
        self.text = text
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(text=self.text)


def _conversation(*turns: tuple[SpeakerRole, str]) -> Conversation:
    conversation = Conversation(call_id="call-1")
    for index, (role, text) in enumerate(turns):
        conversation.add_utterance(
            Utterance(
                utterance_id="1",
                transcript=text,
                speaker_role=role,
                languages=("en",),
                start_time=float(index),
                end_time=float(index) + 0.5,
            )
        )
    return conversation


def _sample_conversation() -> Conversation:
    return _conversation(
        (SpeakerRole.ICR, "How was your recent service experience?"),
        (SpeakerRole.CUSTOMER, "My vehicle was supposed to be ready yesterday."),
        (SpeakerRole.ICR, "Did anyone inform you?"),
        (SpeakerRole.CUSTOMER, "No, nobody called me."),
    )


def _payload(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "label": "NEGATIVE",
        "confidence": 0.91,
        "evidence": "The customer reported a delay and no communication.",
    }
    data.update(overrides)
    return json.dumps(data)


def _analyze(text: Any) -> SentimentResult:
    return LLMSentimentProvider(FakeLLMClient(text)).analyze(_sample_conversation())


def _assert_safe_result(result: SentimentResult) -> None:
    assert result.label is SentimentLabel.NEUTRAL
    assert result.confidence == 0.0
    assert result.evidence


@pytest.mark.parametrize(
    "label, confidence",
    [
        (SentimentLabel.POSITIVE, 0.9),
        (SentimentLabel.NEUTRAL, 0.6),
        (SentimentLabel.NEGATIVE, 0.85),
    ],
)
def test_valid_response_is_parsed(label, confidence):
    result = _analyze(
        _payload(label=label.value, confidence=confidence, evidence="  Some evidence. ")
    )

    assert result == SentimentResult(label, confidence, "Some evidence.")


def test_code_fenced_json_is_accepted():
    result = _analyze(f"```json\n{_payload()}\n```")

    assert result.label is SentimentLabel.NEGATIVE
    assert result.confidence == 0.91


def test_prompt_includes_speaker_roles_and_json_only_instruction():
    client = FakeLLMClient(_payload())

    LLMSentimentProvider(client).analyze(_sample_conversation())

    assert len(client.requests) == 1
    prompt = client.requests[0].prompt
    assert "ICR: How was your recent service experience?" in prompt
    assert "CUSTOMER: My vehicle was supposed to be ready yesterday." in prompt
    assert "ICR: Did anyone inform you?" in prompt
    assert "CUSTOMER: No, nobody called me." in prompt
    assert "ONLY a single JSON object" in prompt


def test_empty_conversation_does_not_call_llm():
    client = FakeLLMClient(_payload())

    result = LLMSentimentProvider(client).analyze(Conversation(call_id="call-1"))

    assert client.requests == []
    assert result == SentimentResult(
        SentimentLabel.NEUTRAL,
        0.0,
        "No conversation content is available to determine sentiment.",
    )


@pytest.mark.parametrize(
    "text",
    ["not json", "", "{", "[]", '["NEGATIVE"]', '"NEGATIVE"', "null", "42", None, 123],
)
def test_malformed_response_returns_safe_result(text):
    _assert_safe_result(_analyze(text))


@pytest.mark.parametrize("label", ["ANGRY", "negative", "", None, 1, ["NEGATIVE"]])
def test_invalid_label_returns_safe_result(label):
    _assert_safe_result(_analyze(_payload(label=label)))


@pytest.mark.parametrize("field", ["label", "confidence", "evidence"])
def test_missing_field_returns_safe_result(field):
    data = json.loads(_payload())
    del data[field]

    _assert_safe_result(_analyze(json.dumps(data)))


@pytest.mark.parametrize("confidence", [-0.1, 1.5, True, False, "0.9", None])
def test_invalid_confidence_returns_safe_result(confidence):
    _assert_safe_result(_analyze(_payload(confidence=confidence)))


@pytest.mark.parametrize("evidence", ["", "   ", None, 123])
def test_invalid_evidence_returns_safe_result(evidence):
    _assert_safe_result(_analyze(_payload(evidence=evidence)))