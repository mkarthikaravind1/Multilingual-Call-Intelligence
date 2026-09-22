from typing import Any

import pytest

from app.ai.emerging_complaint.provider import (
    CallComplaintRecord,
    EmergingComplaintDiscoveryProvider,
    EmergingComplaintDiscoveryRequest,
)
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.emerging_complaint_candidate import EmergingComplaintCandidate
from app.domain.utterance import SpeakerRole, Utterance


def _utterance(index: int = 0) -> Utterance:
    return Utterance(
        utterance_id=str(index + 1),
        transcript=f"Customer statement {index + 1}.",
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=index * 5.0,
        end_time=index * 5.0 + 4.0,
    )


def _record(call_id: str = "call-1", **overrides) -> CallComplaintRecord:
    defaults:dict[str,Any] = dict(
        call_id=call_id,
        utterances=(_utterance(),),
        complaint_coverages=(),
    )
    defaults.update(overrides)
    return CallComplaintRecord(**defaults)


def test_creates_valid_call_complaint_record():
    coverage = ComplaintCoverage(category="Communication", status=ComplaintCoverageStatus.DETECTED)

    record = _record(complaint_coverages=(coverage,))

    assert record.call_id == "call-1"
    assert record.utterances == (_utterance(),)
    assert record.complaint_coverages == (coverage,)


def test_rejects_empty_call_id():
    with pytest.raises(ValueError, match="call_id"):
        _record(call_id="  ")


def test_rejects_non_tuple_utterances():
    with pytest.raises(ValueError, match="utterances"):
        _record(utterances=[_utterance()])  # type: ignore[arg-type]


def test_rejects_utterances_with_wrong_type():
    with pytest.raises(ValueError, match="utterances"):
        _record(utterances=("not an utterance",))  # type: ignore[arg-type]


def test_rejects_non_tuple_complaint_coverages():
    coverage = ComplaintCoverage(category="Communication")
    with pytest.raises(ValueError, match="complaint_coverages"):
        _record(complaint_coverages=[coverage])  # type: ignore[arg-type]


def test_rejects_complaint_coverages_with_wrong_type():
    with pytest.raises(ValueError, match="complaint_coverages"):
        _record(complaint_coverages=("not a coverage",))  # type: ignore[arg-type]


def test_creates_valid_discovery_request():
    request = EmergingComplaintDiscoveryRequest(
        call_records=(_record("call-1"), _record("call-2"))
    )

    assert len(request.call_records) == 2


def test_rejects_empty_call_records():
    with pytest.raises(ValueError, match="must not be empty"):
        EmergingComplaintDiscoveryRequest(call_records=())


def test_rejects_non_tuple_call_records():
    with pytest.raises(ValueError, match="call_records"):
        EmergingComplaintDiscoveryRequest(call_records=[_record()])  # type: ignore[arg-type]


def test_rejects_call_records_with_wrong_type():
    with pytest.raises(ValueError, match="call_records"):
        EmergingComplaintDiscoveryRequest(call_records=("not a record",))  # type: ignore[arg-type]


def test_rejects_duplicate_call_ids():
    with pytest.raises(ValueError, match="duplicate"):
        EmergingComplaintDiscoveryRequest(
            call_records=(_record("call-1"), _record("call-1"))
        )


def test_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        EmergingComplaintDiscoveryProvider()  # type: ignore[abstract]


def test_concrete_provider_satisfies_contract():
    candidate = EmergingComplaintCandidate(
        candidate_id="cand-1",
        proposed_name="Loyalty Program Confusion",
        description="Customers repeatedly confused about how loyalty points are earned.",
        evidence=("Customer asked why points didn't apply.",),
        occurrence_count=2,
        confidence=0.6,
    )

    class FakeDiscoveryProvider(EmergingComplaintDiscoveryProvider):
        def discover(
            self, request: EmergingComplaintDiscoveryRequest
        ) -> tuple[EmergingComplaintCandidate, ...]:
            return (candidate,)

    request = EmergingComplaintDiscoveryRequest(call_records=(_record(),))
    result = FakeDiscoveryProvider().discover(request)

    assert result == (candidate,)