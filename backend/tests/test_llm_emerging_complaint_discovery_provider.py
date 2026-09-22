import json

import pytest

from app.ai.emerging_complaint.llm_provider import LLMEmergingComplaintDiscoveryProvider
from app.ai.emerging_complaint.provider import (
    CallComplaintRecord,
    EmergingComplaintDiscoveryRequest,
)
from app.ai.llm.client import LLMClient, LLMResponse
from app.domain.utterance import SpeakerRole, Utterance


class FakeLLMClient(LLMClient):
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return LLMResponse(text=self._text)


class RaisingLLMClient(LLMClient):
    def complete(self, request):
        raise AssertionError("LLM should not be called")


def _utterance(index: int, transcript: str, role: SpeakerRole = SpeakerRole.CUSTOMER) -> Utterance:
    return Utterance(
        utterance_id=str(index),
        transcript=transcript,
        speaker_role=role,
        languages=("en",),
        start_time=index * 5.0,
        end_time=index * 5.0 + 4.0,
    )


def _record(call_id: str, transcripts: tuple[str, ...], role: SpeakerRole = SpeakerRole.CUSTOMER) -> CallComplaintRecord:
    utterances = tuple(_utterance(i, t, role) for i, t in enumerate(transcripts))
    return CallComplaintRecord(call_id=call_id, utterances=utterances, complaint_coverages=())


def _discover(llm_text: str, *records: CallComplaintRecord):
    provider = LLMEmergingComplaintDiscoveryProvider(FakeLLMClient(llm_text))
    return provider.discover(EmergingComplaintDiscoveryRequest(call_records=records))


def test_empty_result_when_llm_finds_nothing():
    candidates = _discover(
        "[]",
        _record("call-1", ("Everything was fine.",)),
        _record("call-2", ("No issues at all.",)),
    )

    assert candidates == ()


def test_recurring_semantic_pattern_detected():
    response = json.dumps(
        [
            {
                "proposed_name": "Delayed Pickup Reminders",
                "description": "Customers say they weren't reminded their car was ready.",
                "evidence": [
                    {"call_id": "call-1", "quote": "Nobody told me the car was ready."},
                    {"call_id": "call-2", "quote": "I only found out by calling in myself."},
                ],
                "confidence": 0.8,
            }
        ]
    )

    candidates = _discover(
        response,
        _record("call-1", ("Nobody told me the car was ready.",)),
        _record("call-2", ("I only found out by calling in myself.",)),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.proposed_name == "Delayed Pickup Reminders"
    assert candidate.occurrence_count == 2
    assert set(candidate.evidence) == {
        "Nobody told me the car was ready.",
        "I only found out by calling in myself.",
    }


def test_existing_category_excluded():
    response = json.dumps(
        [
            {
                "proposed_name": "hygiene",
                "description": "Matches an existing category.",
                "evidence": [
                    {"call_id": "call-1", "quote": "The car was dirty inside."},
                    {"call_id": "call-2", "quote": "It wasn't cleaned at all."},
                ],
                "confidence": 0.7,
            }
        ]
    )

    candidates = _discover(
        response,
        _record("call-1", ("The car was dirty inside.",)),
        _record("call-2", ("It wasn't cleaned at all.",)),
    )

    assert candidates == ()


def test_fewer_than_two_calls_ignored():
    provider = LLMEmergingComplaintDiscoveryProvider(RaisingLLMClient())
    request = EmergingComplaintDiscoveryRequest(
        call_records=(
            _record("call-1", ("Nobody told me the car was ready.",)),
            _record("call-2", ("Thanks for the update.",), role=SpeakerRole.ICR),
        )
    )

    candidates = provider.discover(request)

    assert candidates == ()


def test_malformed_llm_response():
    candidates = _discover(
        "not valid json at all",
        _record("call-1", ("Nobody told me the car was ready.",)),
        _record("call-2", ("I only found out by calling in myself.",)),
    )

    assert candidates == ()


def test_invalid_candidate_data():
    response = json.dumps(
        [
            {
                "proposed_name": "Delayed Pickup Reminders",
                "description": "Missing evidence field.",
                "confidence": 0.8,
            }
        ]
    )

    candidates = _discover(
        response,
        _record("call-1", ("Nobody told me the car was ready.",)),
        _record("call-2", ("I only found out by calling in myself.",)),
    )

    assert candidates == ()


def test_multiple_candidates_are_returned():
    response = json.dumps(
        [
            {
                "proposed_name": "Delayed Pickup Reminders",
                "description": "Customers weren't reminded the car was ready.",
                "evidence": [
                    {"call_id": "call-1", "quote": "Nobody told me the car was ready."},
                    {"call_id": "call-2", "quote": "I only found out by calling in myself."},
                ],
                "confidence": 0.8,
            },
            {
                "proposed_name": "Loaner Car Fuel Level",
                "description": "Loaner cars are handed over with low fuel.",
                "evidence": [
                    {"call_id": "call-1", "quote": "The loaner had barely any fuel."},
                    {"call_id": "call-3", "quote": "Loaner tank was almost empty."},
                ],
                "confidence": 0.6,
            },
        ]
    )

    candidates = _discover(
        response,
        _record("call-1", ("Nobody told me the car was ready.", "The loaner had barely any fuel.")),
        _record("call-2", ("I only found out by calling in myself.",)),
        _record("call-3", ("Loaner tank was almost empty.",)),
    )

    proposed_names = {c.proposed_name for c in candidates}
    assert len(candidates) == 2
    assert proposed_names == {"Delayed Pickup Reminders", "Loaner Car Fuel Level"}
    assert len({c.candidate_id for c in candidates}) == 2