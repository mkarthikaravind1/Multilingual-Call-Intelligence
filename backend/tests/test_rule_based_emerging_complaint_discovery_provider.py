import pytest

from app.ai.emerging_complaint.provider import (
    CallComplaintRecord,
    EmergingComplaintDiscoveryRequest,
)
from app.ai.emerging_complaint.rule_based_provider import (
    RuleBasedEmergingComplaintDiscoveryProvider,
)
from app.domain.utterance import SpeakerRole, Utterance


def _utterance(index: int, transcript: str, role: SpeakerRole = SpeakerRole.CUSTOMER) -> Utterance:
    return Utterance(
        utterance_id=str(index),
        transcript=transcript,
        speaker_role=role,
        languages=("en",),
        start_time=index * 5.0,
        end_time=index * 5.0 + 4.0,
    )


def _record(call_id: str, transcripts: tuple[str, ...]) -> CallComplaintRecord:
    utterances = tuple(_utterance(i, t) for i, t in enumerate(transcripts))
    return CallComplaintRecord(call_id=call_id, utterances=utterances, complaint_coverages=())


def _discover(*records: CallComplaintRecord):
    provider = RuleBasedEmergingComplaintDiscoveryProvider()
    return provider.discover(EmergingComplaintDiscoveryRequest(call_records=records))


def test_no_candidates_when_nothing_recurs():
    candidates = _discover(
        _record("call-1", ("The tyres were noisy after the service.",)),
        _record("call-2", ("They forgot to top up the coolant.",)),
    )

    assert candidates == ()


def test_one_off_pattern_is_ignored():
    candidates = _discover(
        _record(
            "call-1",
            (
                "The technician never called me back.",
                "The technician never called me back.",
            ),
        ),
        _record("call-2", ("Everything about the visit was fine.",)),
    )

    assert candidates == ()


def test_recurring_pattern_across_two_calls_is_detected():
    candidates = _discover(
        _record("call-1", ("The technician never called me back.",)),
        _record("call-2", ("the technician never called me back!",)),
    )

    assert len(candidates) == 1
    assert candidates[0].proposed_name == "The Technician Never Called Me Back"


def test_existing_complaint_categories_are_not_proposed():
    candidates = _discover(
        _record("call-1", ("Turnaround Time.",)),
        _record("call-2", ("turnaround time!",)),
    )

    assert candidates == ()


def test_occurrence_count_counts_every_matching_utterance():
    candidates = _discover(
        _record(
            "call-1",
            (
                "They never returned my calls.",
                "they never returned my calls",
            ),
        ),
        _record("call-2", ("They never returned my calls!",)),
        _record("call-3", ("Unrelated remark about parking.",)),
    )

    assert len(candidates) == 1
    assert candidates[0].occurrence_count == 3


def test_evidence_preserves_original_transcripts():
    call_1_text = "The loaner car had an empty tank."
    call_2_text = "the loaner car had an empty tank"

    candidates = _discover(
        _record("call-1", (call_1_text,)),
        _record("call-2", (call_2_text,)),
    )

    assert len(candidates) == 1
    assert set(candidates[0].evidence) == {call_1_text, call_2_text}


def test_confidence_reflects_share_of_calls_with_the_pattern():
    candidates = _discover(
        _record("call-1", ("They never returned my calls.",)),
        _record("call-2", ("they never returned my calls",)),
        _record("call-3", ("Unrelated remark about parking.",)),
    )

    assert len(candidates) == 1
    assert candidates[0].confidence == pytest.approx(2 / 3)


def test_multiple_independent_patterns_are_each_detected():
    candidates = _discover(
        _record(
            "call-1",
            ("The technician never called me back.", "The loaner car had an empty tank."),
        ),
        _record(
            "call-2",
            ("the technician never called me back", "the loaner car had an empty tank"),
        ),
    )

    proposed_names = {c.proposed_name for c in candidates}
    assert len(candidates) == 2
    assert proposed_names == {
        "The Technician Never Called Me Back",
        "The Loaner Car Had An Empty Tank",
    }


def test_non_customer_utterances_are_ignored():
    _NON_CUSTOMER_ROLE = next(role for role in SpeakerRole if role != SpeakerRole.CUSTOMER)
    candidates = _discover(
        
        _record("call-1", ()),
        
        CallComplaintRecord(
            call_id="call-1b",
            
            utterances=(
                _utterance(0, "We apologize for the delay, sir.", role=_NON_CUSTOMER_ROLE),
                _utterance(1, "We apologize for the delay, sir.", role=_NON_CUSTOMER_ROLE),
            ),
            complaint_coverages=(),
        ),
    )

    assert candidates == ()


def test_candidate_id_is_stable_for_the_same_pattern():
    records = (
        _record("call-1", ("The technician never called me back.",)),
        _record("call-2", ("the technician never called me back",)),
    )

    first = _discover(*records)
    second = _discover(*records)

    assert first[0].candidate_id == second[0].candidate_id