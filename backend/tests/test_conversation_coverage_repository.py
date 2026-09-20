import pytest

from app.domain.conversation_coverage import ConversationCoverage
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)


def test_saved_coverage_can_be_retrieved():
    repository = InMemoryConversationCoverageRepository()
    coverage = ConversationCoverage(call_id="call-1")

    repository.save(coverage)

    assert repository.get("call-1") is coverage


def test_missing_coverage_returns_none():
    assert InMemoryConversationCoverageRepository().get("unknown") is None


def test_saving_again_replaces_existing_coverage():
    repository = InMemoryConversationCoverageRepository()
    repository.save(ConversationCoverage(call_id="call-1"))
    replacement = ConversationCoverage(call_id="call-1")

    repository.save(replacement)

    assert repository.get("call-1") is replacement


def test_coverages_are_isolated_by_call_id():
    repository = InMemoryConversationCoverageRepository()
    first = ConversationCoverage(call_id="call-1")
    second = ConversationCoverage(call_id="call-2")

    repository.save(first)
    repository.save(second)

    assert repository.get("call-1") is first
    assert repository.get("call-2") is second


def test_abstract_repository_cannot_be_instantiated():
    with pytest.raises(TypeError):
        ConversationCoverageRepository()  # type: ignore