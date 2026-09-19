import ast
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.services import complaint_analysis_service as service_module
from app.services.complaint_analysis_service import ComplaintAnalysisService

_STEPS_TO = {
    ComplaintCoverageStatus.DETECTED: ("detect",),
    ComplaintCoverageStatus.PROBED: ("detect", "probe"),
    ComplaintCoverageStatus.COVERED: ("detect", "probe", "cover"),
    ComplaintCoverageStatus.RESOLVED: ("detect", "probe", "cover", "resolve"),
    ComplaintCoverageStatus.UNRESOLVED: ("detect", "probe", "cover", "mark_unresolved"),
}


class FakeComplaintProvider(ComplaintDetectionProvider):
    def __init__(self, results: list[ComplaintDetectionResult] | None = None) -> None:
        self.results = results or []
        self.received_conversation: Conversation | None = None
        self.call_count = 0

    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        self.call_count += 1
        self.received_conversation = conversation
        return list(self.results)


def _detection(
    category: str = "Turnaround Time",
    confidence: float = 0.93,
    evidence: str = "The car was delivered two days late.",
) -> ComplaintDetectionResult:
    return ComplaintDetectionResult(category, confidence, evidence)


def _conversation() -> Conversation:
    return Conversation(call_id="call-1")


def _coverage() -> ConversationCoverage:
    return ConversationCoverage(call_id="call-1")


def _coverage_with(
    category: str, status: ComplaintCoverageStatus
) -> ConversationCoverage:
    coverage = _coverage()
    complaint = coverage.add(category)
    for step in _STEPS_TO[status]:
        getattr(complaint, step)()
    return coverage


def _status(coverage: ConversationCoverage, category: str) -> ComplaintCoverageStatus:
    complaint = coverage.get(category)
    assert complaint is not None
    return complaint.status


def _snapshot(coverage: ConversationCoverage) -> list[tuple[str, ComplaintCoverageStatus]]:
    return [(c.category, c.status) for c in coverage.complaints]


def _analyze(
    results: list[ComplaintDetectionResult], coverage: ConversationCoverage
) -> ConversationCoverage:
    return ComplaintAnalysisService(FakeComplaintProvider(results)).analyze(
        _conversation(), coverage
    )


def test_one_detected_complaint_creates_detected_coverage():
    coverage = _coverage()

    _analyze([_detection()], coverage)

    assert _snapshot(coverage) == [
        ("Turnaround Time", ComplaintCoverageStatus.DETECTED)
    ]


def test_multiple_detected_complaints_create_multiple_categories():
    coverage = _coverage()

    _analyze(
        [
            _detection("Turnaround Time", 0.93),
            _detection("Communication", 0.87, "Nobody informed me about the delay."),
        ],
        coverage,
    )

    assert _snapshot(coverage) == [
        ("Turnaround Time", ComplaintCoverageStatus.DETECTED),
        ("Communication", ComplaintCoverageStatus.DETECTED),
    ]


def test_empty_detection_leaves_empty_coverage_unchanged():
    coverage = _coverage()

    _analyze([], coverage)

    assert coverage.complaints == ()


def test_empty_detection_leaves_existing_coverage_unchanged():
    coverage = _coverage_with("Turnaround Time", ComplaintCoverageStatus.PROBED)
    before = _snapshot(coverage)

    _analyze([], coverage)

    assert _snapshot(coverage) == before


@pytest.mark.parametrize(
    "status",
    [
        ComplaintCoverageStatus.PROBED,
        ComplaintCoverageStatus.COVERED,
        ComplaintCoverageStatus.RESOLVED,
        ComplaintCoverageStatus.UNRESOLVED,
    ],
    ids=lambda status: status.value,
)
def test_existing_later_status_is_not_reset_by_detection(status):
    coverage = _coverage_with("Turnaround Time", status)

    _analyze([_detection("Turnaround Time")], coverage)

    assert _status(coverage, "Turnaround Time") is status
    assert len(coverage.complaints) == 1


def test_new_detection_alongside_progressed_complaint():
    coverage = _coverage_with("Turnaround Time", ComplaintCoverageStatus.PROBED)

    _analyze(
        [
            _detection("Turnaround Time"),
            _detection("Communication", 0.87, "Nobody informed me about the delay."),
        ],
        coverage,
    )

    assert _status(coverage, "Turnaround Time") is ComplaintCoverageStatus.PROBED
    assert _status(coverage, "Communication") is ComplaintCoverageStatus.DETECTED


def test_existing_not_raised_complaint_becomes_detected():
    coverage = _coverage()
    coverage.add("Cost")

    _analyze([_detection("Cost")], coverage)

    assert _status(coverage, "Cost") is ComplaintCoverageStatus.DETECTED


def test_repeated_analysis_keeps_detected_status_without_error():
    service = ComplaintAnalysisService(FakeComplaintProvider([_detection()]))
    conversation = _conversation()
    coverage = _coverage()

    service.analyze(conversation, coverage)
    service.analyze(conversation, coverage)

    assert _snapshot(coverage) == [
        ("Turnaround Time", ComplaintCoverageStatus.DETECTED)
    ]


def test_duplicate_categories_from_provider_create_one_complaint():
    coverage = _coverage()

    _analyze([_detection("Cost"), _detection("Cost", 0.5, "Too expensive.")], coverage)

    assert _snapshot(coverage) == [("Cost", ComplaintCoverageStatus.DETECTED)]


def test_service_returns_the_updated_coverage():
    coverage = _coverage()

    result = _analyze([_detection()], coverage)

    assert result is coverage


def test_injected_detector_is_called_with_the_conversation():
    provider = FakeComplaintProvider([_detection()])
    service = ComplaintAnalysisService(provider)
    conversation = _conversation()

    service.analyze(conversation, _coverage())

    assert provider.call_count == 1
    assert provider.received_conversation is conversation


def test_unsupported_category_is_rejected_by_domain_validation():
    invalid = cast(
        ComplaintDetectionResult,
        SimpleNamespace(category="Banana", confidence=0.9, evidence="evidence"),
    )
    coverage = _coverage()

    with pytest.raises(ValueError, match="Unsupported complaint category"):
        _analyze([invalid], coverage)

    assert coverage.complaints == ()
    assert coverage.get("Other") is None


def test_mismatched_call_ids_are_rejected_before_detection():
    provider = FakeComplaintProvider([_detection()])
    service = ComplaintAnalysisService(provider)

    with pytest.raises(ValueError, match="cannot be updated"):
        service.analyze(Conversation(call_id="a"), ConversationCoverage(call_id="b"))

    assert provider.call_count == 0


def test_service_does_not_import_llm_or_groq_code():
    tree = ast.parse(Path(service_module.__file__).read_text())
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for name in [node.module or "", *(alias.name for alias in node.names)]
    ]

    forbidden = ("groq", "app.ai.llm", "llm_provider", "llmclient")
    assert not any(bad in name.lower() for name in imported for bad in forbidden)