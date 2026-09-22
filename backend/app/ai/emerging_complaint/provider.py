from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.complaint_coverage import ComplaintCoverage
from app.domain.emerging_complaint_candidate import EmergingComplaintCandidate
from app.domain.utterance import Utterance


@dataclass(frozen=True)
class CallComplaintRecord:
    """One completed call's contribution to emerging-complaint discovery:
    its utterances and the complaint categories already recognized in it.

    Deliberately not the full Conversation model — discovery may run over
    a filtered subset of utterances (e.g. only customer turns, or only
    turns near a detected complaint) rather than a whole chronological
    transcript, and doesn't need Conversation's status/timing bookkeeping.
    """

    call_id: str
    utterances: tuple[Utterance, ...]
    complaint_coverages: tuple[ComplaintCoverage, ...]

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")

        if not isinstance(self.utterances, tuple) or not all(
            isinstance(u, Utterance) for u in self.utterances
        ):
            raise ValueError("utterances must be a tuple of Utterance.")

        if not isinstance(self.complaint_coverages, tuple) or not all(
            isinstance(c, ComplaintCoverage) for c in self.complaint_coverages
        ):
            raise ValueError("complaint_coverages must be a tuple of ComplaintCoverage.")


@dataclass(frozen=True)
class EmergingComplaintDiscoveryRequest:
    """Bundles the multi-call data a provider needs to spot a pattern that
    recurs across calls but doesn't map to an existing complaint category.
    Unlike single-call requests (e.g. PostCallSummaryRequest), this is
    inherently cross-call, so it carries many CallComplaintRecords rather
    than one call's data.
    """

    call_records: tuple[CallComplaintRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.call_records, tuple) or not all(
            isinstance(record, CallComplaintRecord) for record in self.call_records
        ):
            raise ValueError("call_records must be a tuple of CallComplaintRecord.")

        if not self.call_records:
            raise ValueError("call_records must not be empty.")

        call_ids = [record.call_id for record in self.call_records]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("call_records must not contain duplicate call_id values.")


class EmergingComplaintDiscoveryProvider(ABC):
    @abstractmethod
    def discover(
        self, request: EmergingComplaintDiscoveryRequest
    ) -> tuple[EmergingComplaintCandidate, ...]:
        raise NotImplementedError