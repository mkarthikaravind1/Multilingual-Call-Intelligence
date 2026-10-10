from abc import ABC, abstractmethod
from collections.abc import Collection

from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence


class LearningEvidenceRepository(ABC):
    @abstractmethod
    def save(self, evidence: LearningEvidence) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, evidence_id: str) -> LearningEvidence | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[LearningEvidence, ...]:
        raise NotImplementedError

    # The table gains several rows per call (every AI output is recorded).
    # The reads below ask for the part they need; a database-backed
    # repository answers them with a query instead of loading everything.

    def list_page(self, limit: int, offset: int = 0) -> tuple[LearningEvidence, ...]:
        """Evidence, newest first."""
        newest_first = sorted(
            self.list_all(), key=lambda e: (e.created_at, e.evidence_id), reverse=True
        )
        return tuple(newest_first[offset : offset + limit])

    def count(self) -> int:
        return len(self.list_all())

    def list_judged(self) -> tuple[LearningEvidence, ...]:
        """Evidence that carries a human judgement or an expected value:
        everything except the plain record of what the AI said."""
        return tuple(
            e
            for e in self.list_all()
            if e.human_correction is not None or e.expected_value is not None
        )

    def prediction_calls(self) -> dict[tuple[LearningComponent, str], int]:
        """(component, the AI's output, case-folded) -> on how many calls
        the AI gave that output."""
        calls: dict[tuple[LearningComponent, str], set[str]] = {}
        for e in self.list_all():
            if e.evidence_type is EvidenceType.AI_PREDICTION and e.actual_value is not None:
                key = (e.component, e.actual_value.strip().casefold())
                calls.setdefault(key, set()).add(e.call_id)
        return {key: len(call_ids) for key, call_ids in calls.items()}

    def list_for_outputs(
        self, component: LearningComponent, actual_values: Collection[str]
    ) -> tuple[LearningEvidence, ...]:
        """Evidence about these outputs of one component (as the AI gave
        them, exactly)."""
        wanted = set(actual_values)
        return tuple(
            e for e in self.list_all() if e.component is component and e.actual_value in wanted
        )


class InMemoryLearningEvidenceRepository(LearningEvidenceRepository):
    def __init__(self) -> None:
        self._evidence: dict[str, LearningEvidence] = {}

    def save(self, evidence: LearningEvidence) -> None:
        self._evidence[evidence.evidence_id] = evidence

    def get(self, evidence_id: str) -> LearningEvidence | None:
        return self._evidence.get(evidence_id)

    def list_all(self) -> tuple[LearningEvidence, ...]:
        return tuple(self._evidence.values())
