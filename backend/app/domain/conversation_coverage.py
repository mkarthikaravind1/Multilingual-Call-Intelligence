from dataclasses import dataclass, field
from app.domain.complaint_category import require_category_name
from app.domain.complaint_coverage import ComplaintCoverage

@dataclass
class ConversationCoverage:
    call_id: str
    _complaints: dict[str, ComplaintCoverage] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")

    @property
    def complaints(self) -> tuple[ComplaintCoverage, ...]:
        return tuple(self._complaints.values())

    def get(self, category: str) -> ComplaintCoverage | None:
        return self._complaints.get(category)

    def add(self, category: str) -> ComplaintCoverage:
        require_category_name(category)

        if category in self._complaints:
            raise ValueError(
                f"Complaint category already exists: {category!r}."
            )

        complaint = ComplaintCoverage(category)
        self._complaints[category] = complaint
        return complaint

    def get_or_add(self, category: str) -> ComplaintCoverage:
        complaint = self.get(category)

        if complaint is not None:
            return complaint

        return self.add(category)

    def uncovered_complaints(self) -> tuple[ComplaintCoverage, ...]:
        return tuple(
            complaint
            for complaint in self._complaints.values()
            if complaint.status.value in {"detected", "probed"}
        )