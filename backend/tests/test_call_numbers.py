"""Call ids: "CALL-" and a running number for every kind of call, and the
one-off renaming of calls made before that."""

import json
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.domain.call_number import (
    InMemoryCallNumbers,
    call_number,
    format_call_id,
)
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import (
    CallRecordingModel,
    ConversationModel,
    EmergingComplaintCandidateModel,
    LearningEvidenceModel,
    UtteranceModel,
)
from app.security.stream_token import (
    create_stream_token,
    is_test_call_stream,
    is_valid_stream_token,
)
from app.services.call_renumbering import renumber_calls
from app.services.call_service import CallService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.conversation_service import ConversationService
from app.services.telephony_call_mapping_repository import InMemoryTelephonyCallMappingRepository
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.provider import InboundCallEvent


def test_a_call_id_is_the_prefix_and_a_padded_number():
    assert format_call_id(1) == "CALL-000001"
    assert format_call_id(123) == "CALL-000123"
    # Past six digits the number is written in full.
    assert format_call_id(1234567) == "CALL-1234567"
    assert [call_number(i) for i in ("CALL-000123", "CALL-1234567")] == [123, 1234567]
    assert [call_number(i) for i in ("test-1", "CALL-", "call-000001", "CALL-12a", "XCALL-1")] == [None] * 5


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "7"])
def test_a_call_number_is_a_whole_number_from_one(bad):
    with pytest.raises(ValueError):
        format_call_id(bad)


def test_numbers_are_never_handed_out_twice():
    numbers = InMemoryCallNumbers()
    taken: list[int] = []

    def take() -> None:
        for _ in range(200):
            taken.append(numbers.next())

    threads = [threading.Thread(target=take) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(taken) == list(range(1, 1601))


def test_phone_and_test_calls_share_one_counter_with_calls_started_by_hand():
    calls = CallService(ConversationService(InMemoryConversationRepository()))
    telephony = TelephonyCallService(calls, InMemoryTelephonyCallMappingRepository())

    by_phone = telephony.start_call_from_provider("plivo", InboundCallEvent("uuid-1", "+91123", "+91456"))
    by_hand = calls.new_call_id()
    replayed = telephony.start_call_from_provider("test", InboundCallEvent("test-1", "", "test-line"))
    # The provider's answer webhook sent again is the same call, not a new number.
    again = telephony.start_call_from_provider("plivo", InboundCallEvent("uuid-1", "+91123", "+91456"))

    assert (by_phone, by_hand, replayed, again) == (
        "CALL-000001",
        "CALL-000002",
        "CALL-000003",
        "CALL-000001",
    )


def test_only_a_test_calls_token_marks_its_stream_as_a_test_call():
    ordinary = create_stream_token("CALL-000001")
    test_call = create_stream_token("CALL-000001", test_call=True)

    assert is_valid_stream_token(test_call, "CALL-000001")
    assert is_test_call_stream(test_call, "CALL-000001")
    assert not is_test_call_stream(ordinary, "CALL-000001")
    assert not is_test_call_stream(test_call, "CALL-000002")
    assert not is_test_call_stream(None, "CALL-000001")
    assert not is_test_call_stream(test_call + "x", "CALL-000001")


# ---- Renaming older calls ----


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


def _call(session, call_id: str, start_time: float) -> None:
    session.add(ConversationModel(call_id=call_id, status="completed", start_time=start_time))
    session.add(
        UtteranceModel(
            utterance_id=f"{call_id}-u1",
            call_id=call_id,
            transcript="hello",
            speaker_role="CUSTOMER",
            languages=["en"],
            start_time=0.0,
            end_time=1.0,
        )
    )
    session.add(
        LearningEvidenceModel(
            evidence_id=f"ev-{call_id}",
            call_id=call_id,
            evidence_type="ai_prediction",
            component="sentiment_analysis",
            description="NEUTRAL",
            created_at=start_time,
        )
    )


def _column(engine, sql: str) -> list:
    with engine.connect() as connection:
        return list(connection.execute(text(sql)).scalars())


def _seed(engine) -> None:
    with Session(engine) as session, session.begin():
        _call(session, "test-late", 300.0)
        _call(session, "manual-early", 100.0)
        _call(session, "plivo-middle", 200.0)
        session.add(
            EmergingComplaintCandidateModel(
                candidate_id="theme-1",
                proposed_name="A Theme",
                description="d",
                evidence=["q"],
                call_ids=["test-late", "gone-call", "manual-early"],
                occurrence_count=2,
                confidence=0.5,
                status="pending_review",
                first_seen_at=1.0,
                last_seen_at=1.0,
            )
        )


def test_older_calls_are_numbered_oldest_first_everywhere(engine):
    _seed(engine)

    result = renumber_calls(engine, apply=True)

    assert result.renamed == {
        "manual-early": "CALL-000001",
        "plivo-middle": "CALL-000002",
        "test-late": "CALL-000003",
    }
    assert (result.applied, result.left_behind, result.kept) == (True, 0, {})
    assert _column(engine, "SELECT call_id FROM conversations ORDER BY start_time") == [
        "CALL-000001",
        "CALL-000002",
        "CALL-000003",
    ]
    # Lines stay with their call (and keep their own ids).
    assert _column(engine, "SELECT call_id FROM utterances WHERE utterance_id = 'test-late-u1'") == ["CALL-000003"]
    assert _column(engine, "SELECT count(*) FROM utterances") == [3]
    assert sorted(_column(engine, "SELECT call_id FROM learning_evidence")) == [
        "CALL-000001",
        "CALL-000002",
        "CALL-000003",
    ]
    # A theme's list of calls follows; an id that is no call is left as it is.
    (ids,) = _column(engine, "SELECT call_ids FROM emerging_complaint_candidates")
    assert json.loads(ids) == ["CALL-000003", "gone-call", "CALL-000001"]
    assert result.rows_changed["utterances.call_id"] == 3


def test_a_dry_run_reports_and_changes_nothing(engine):
    _seed(engine)

    result = renumber_calls(engine)

    assert (len(result.renamed), result.applied, result.left_behind) == (3, False, 0)
    assert sorted(_column(engine, "SELECT call_id FROM conversations")) == [
        "manual-early",
        "plivo-middle",
        "test-late",
    ]
    assert sorted(_column(engine, "SELECT call_id FROM utterances")) == [
        "manual-early",
        "plivo-middle",
        "test-late",
    ]


def test_numbering_continues_after_calls_that_already_have_a_number(engine):
    with Session(engine) as session, session.begin():
        _call(session, "CALL-000007", 50.0)
        _call(session, "test-old", 10.0)

    first = renumber_calls(engine, apply=True)
    again = renumber_calls(engine, apply=True)

    assert first.renamed == {"test-old": "CALL-000008"}
    assert again.renamed == {}
    assert sorted(_column(engine, "SELECT call_id FROM conversations")) == ["CALL-000007", "CALL-000008"]


def test_a_call_with_a_recording_keeps_its_id(engine):
    with Session(engine) as session, session.begin():
        _call(session, "test-recorded", 10.0)
        _call(session, "test-plain", 20.0)
        session.add(
            CallRecordingModel(
                call_id="test-recorded",
                file_name="f.enc",
                duration_seconds=1.0,
                size_bytes=1,
                sample_rate=16000,
                channels=1,
                created_at=1.0,
                delete_after=2.0,
            )
        )

    result = renumber_calls(engine, apply=True)

    assert result.renamed == {"test-plain": "CALL-000001"}
    assert result.kept == {"test-recorded": "has a row in call_recordings"}
    assert sorted(_column(engine, "SELECT call_id FROM conversations")) == ["CALL-000001", "test-recorded"]
