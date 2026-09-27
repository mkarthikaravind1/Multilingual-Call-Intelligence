from abc import ABC, abstractmethod

from app.domain.post_call_summary import PostCallSummary


class PostCallSummaryRepository(ABC):
    @abstractmethod
    def get(self, call_id: str) -> PostCallSummary | None:
        raise NotImplementedError

    @abstractmethod
    def add_if_absent(self, summary: PostCallSummary) -> PostCallSummary:
        """Store the summary unless one already exists for its call_id.

        Returns the stored summary, which is the earlier one if another
        attempt got there first — a call keeps exactly one summary.
        """
        raise NotImplementedError


class InMemoryPostCallSummaryRepository(PostCallSummaryRepository):
    def __init__(self) -> None:
        self._summaries: dict[str, PostCallSummary] = {}

    def get(self, call_id: str) -> PostCallSummary | None:
        return self._summaries.get(call_id)

    def add_if_absent(self, summary: PostCallSummary) -> PostCallSummary:
        return self._summaries.setdefault(summary.call_id, summary)
