# backend/tests/test_complaint_lifecycle_integration_service.py

import pytest

from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.complaint_lifecycle_service import ComplaintLifecycleService
from app.services.complaint_lifecycle_integration_service import (
    ComplaintLifecycleIntegrationService,
)


class FakeDetection:
    def __init__(self, category: str) -> None:
        self.category = category

from app.ai.complaint.provider import ComplaintDetectionProvider


class FakeComplaintDetectionProvider(ComplaintDetectionProvider):
    def __init__(self, categories: list[str]) -> None:
        self._categories = categories

    def detect(self, conversation):
        return [FakeDetection(category) for category in self._categories]


class InMemoryComplaintLifecycleRepository(ComplaintLifecycleRepository):
    def __init__(self) -> None:
        self._records = {}

    def save(self, record) -> None:
        self._records[record.complaint_id] = record

    def get(self, complaint_id: str):
        return self._records.get(complaint_id)


def build_service(categories: list[str]):
    repository = InMemoryComplaintLifecycleRepository()
    integration = ComplaintLifecycleIntegrationService(
        complaint_analysis_service=ComplaintAnalysisService(
            FakeComplaintDetectionProvider(categories)
        ),
        complaint_lifecycle_service=ComplaintLifecycleService(repository),
    )
    return integration, repository


def test_first_detection_creates_lifecycle_record():
    integration, repository = build_service(["Cost"])
    conversation = Conversation(call_id="call-1")
    coverage = ConversationCoverage(call_id="call-1")

    integration.analyze(conversation, coverage, at=0.0)

    record = repository.get("call-1:Cost")
    assert record is not None
    assert record.status.value == "detected"


def test_repeated_detection_reuses_same_lifecycle_record():
    integration, repository = build_service(["Cost"])
    conversation = Conversation(call_id="call-1")
    coverage = ConversationCoverage(call_id="call-1")

    integration.analyze(conversation, coverage, at=0.0)
    integration.analyze(conversation, coverage, at=1.0)

    assert len(repository._records) == 1
    record = repository.get("call-1:Cost")
    assert record is not None
    assert record.status.value == "detected"
    assert record.first_detected_at == 0.0


def test_detected_probed_covered_transitions():
    integration, repository = build_service(["Cost"])
    conversation = Conversation(call_id="call-1")
    coverage = ConversationCoverage(call_id="call-1")

    integration.analyze(conversation, coverage, at=0.0)
    coverage.get_or_add("Cost").probe()
    integration.analyze(conversation, coverage, at=5.0)
    assert repository.get("call-1:Cost").status.value == "probed" # type: ignore

    coverage.get_or_add("Cost").cover()
    integration.analyze(conversation, coverage, at=10.0)
    assert repository.get("call-1:Cost").status.value == "covered" # type: ignore


def test_resolved_path():
    integration, repository = build_service(["Cost"])
    conversation = Conversation(call_id="call-1")
    coverage = ConversationCoverage(call_id="call-1")

    integration.analyze(conversation, coverage, at=0.0)
    coverage.get_or_add("Cost").probe()
    coverage.get_or_add("Cost").cover()
    coverage.get_or_add("Cost").resolve()
    integration.analyze(conversation, coverage, at=10.0)

    assert repository.get("call-1:Cost").status.value == "resolved" # type: ignore


def test_unresolved_path():
    integration, repository = build_service(["Hygiene"])
    conversation = Conversation(call_id="call-2")
    coverage = ConversationCoverage(call_id="call-2")

    integration.analyze(conversation, coverage, at=0.0)
    coverage.get_or_add("Hygiene").probe()
    coverage.get_or_add("Hygiene").cover()
    coverage.get_or_add("Hygiene").mark_unresolved()
    integration.analyze(conversation, coverage, at=10.0)

    assert repository.get("call-2:Hygiene").status.value == "unresolved" # type: ignore


def test_lifecycle_state_persisted():
    integration, repository = build_service(["Cost"])
    conversation = Conversation(call_id="call-1")
    coverage = ConversationCoverage(call_id="call-1")

    integration.analyze(conversation, coverage, at=0.0)

    persisted = repository.get("call-1:Cost")
    assert persisted is not None
    assert persisted.call_id == "call-1"
    assert persisted.category == "Cost"