from dataclasses import dataclass

from app.ai.sentiment.provider import SentimentResult
from app.core.constants import COMPLAINT_CATEGORIES, SUPPORTED_LANGUAGES
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.service_estimate import ServiceEstimate


def _require_str_tuple(value: tuple, field_name: str) -> None:
    if not isinstance(value, tuple) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field_name} must be a tuple of non-empty strings.")


@dataclass(frozen=True)
class ComplaintSummary:
    category: str
    description: str
    status: ComplaintCoverageStatus
    evidence: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.category not in COMPLAINT_CATEGORIES:
            raise ValueError(f"Unsupported complaint category: {self.category!r}.")

        if not self.description.strip():
            raise ValueError("description must not be empty.")

        if not isinstance(self.status, ComplaintCoverageStatus):
            raise TypeError(
                f"status must be a ComplaintCoverageStatus, got {type(self.status).__name__}."
            )

        if not self.evidence.strip():
            raise ValueError("evidence must not be empty.")

        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
                raise TypeError(
                    f"confidence must be a number, got {type(self.confidence).__name__}."
                )
            if not (0.0 <= self.confidence <= 1.0):
                raise ValueError("confidence must be between 0.0 and 1.0.")


@dataclass(frozen=True)
class PostCallSummary:
    call_id: str
    overall_summary: str
    languages: tuple[str, ...]
    sentiment: SentimentResult
    complaints: tuple[ComplaintSummary, ...]
    unresolved_issues: tuple[str, ...]
    actions_promised: tuple[str, ...]
    follow_up_required: bool
    customer_summary: str
    # Optional: not every call yields a cost/service estimate.
    service_estimate: ServiceEstimate | None = None

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")

        if not self.overall_summary.strip():
            raise ValueError("overall_summary must not be empty.")

        if not isinstance(self.languages, tuple) or not self.languages:
            raise ValueError("languages must be a non-empty tuple.")
        for lang in self.languages:
            if lang not in SUPPORTED_LANGUAGES:
                raise ValueError(
                    f"Unsupported language code: {lang!r}. Must be one of {SUPPORTED_LANGUAGES}."
                )

        if not isinstance(self.sentiment, SentimentResult):
            raise TypeError(
                f"sentiment must be a SentimentResult, got {type(self.sentiment).__name__}."
            )

        if not isinstance(self.complaints, tuple) or not all(
            isinstance(c, ComplaintSummary) for c in self.complaints
        ):
            raise ValueError("complaints must be a tuple of ComplaintSummary.")

        _require_str_tuple(self.unresolved_issues, "unresolved_issues")
        _require_str_tuple(self.actions_promised, "actions_promised")

        if isinstance(self.follow_up_required, bool) is False:
            raise TypeError(
                f"follow_up_required must be a bool, got {type(self.follow_up_required).__name__}."
            )

        if not self.customer_summary.strip():
            raise ValueError("customer_summary must not be empty.")

        if self.service_estimate is not None and not isinstance(
            self.service_estimate, ServiceEstimate
        ):
            raise TypeError(
                f"service_estimate must be a ServiceEstimate or None, "
                f"got {type(self.service_estimate).__name__}."
            )