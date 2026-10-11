"""How the complaint report is laid out when it is exported, as an
administrator has set it: the company name and title printed on it, which
sections it has and in what order, and which columns its list of
complaints carries.

One layout for the whole installation. Until one is saved, every section
and column is there in the built-in order.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

# section id -> (its name, whether the PDF has it). The list of complaints
# is too wide to print: it is in the Excel and CSV exports only.
SECTIONS: dict[str, tuple[str, bool]] = {
    "categories": ("Complaints by category", True),
    "trend": ("Trend", True),
    "locations": ("Category by location", True),
    "root_causes": ("Root causes", True),
    "tone": ("Tone", True),
    "tone_trend": ("Tone trend", True),
    "complaints": ("List of complaints", False),
}
# column id -> its heading in the list of complaints.
COLUMNS: dict[str, str] = {
    "call_id": "Call ID",
    "call_date": "Call date",
    "location": "Location",
    "executive": "Executive",
    "direction": "Direction",
    "tone": "Tone",
    "category": "Category",
    "status": "Status",
    "description": "Description",
    "customer_words": "Customer's words",
}
DEFAULT_TITLE = "Complaint report"
MAX_NAME_LENGTH = 100


class ReportLayoutError(ValueError):
    """A layout that cannot be used (the message says why)."""


@dataclass(frozen=True)
class ReportLayout:
    # Printed above the title; empty: nothing is printed.
    company_name: str = ""
    title: str = DEFAULT_TITLE
    # The sections the report has, in the order they appear.
    sections: tuple[str, ...] = tuple(SECTIONS)
    # The columns of the list of complaints, in order.
    columns: tuple[str, ...] = tuple(COLUMNS)

    def has(self, section: str) -> bool:
        return section in self.sections


DEFAULT_LAYOUT = ReportLayout()


def validated(
    company_name: str, title: str, sections: list[str], columns: list[str]
) -> ReportLayout:
    """The layout, tidied; raises ReportLayoutError when it cannot be used."""
    company_name = " ".join((company_name or "").split())
    title = " ".join((title or "").split())
    if not title:
        raise ReportLayoutError("The report needs a title.")
    if len(title) > MAX_NAME_LENGTH or len(company_name) > MAX_NAME_LENGTH:
        raise ReportLayoutError(
            f"The title and the company name can be at most {MAX_NAME_LENGTH} characters."
        )
    for chosen, known, what in ((sections, SECTIONS, "section"), (columns, COLUMNS, "column")):
        unknown = [item for item in chosen if item not in known]
        if unknown:
            raise ReportLayoutError(f"Unknown {what}: {', '.join(unknown)}.")
        if len(set(chosen)) != len(chosen):
            raise ReportLayoutError(f"A {what} is listed twice.")
        if not chosen:
            raise ReportLayoutError(f"The report needs at least one {what}.")
    return ReportLayout(company_name, title, tuple(sections), tuple(columns))


@dataclass(frozen=True)
class SavedLayout:
    layout: ReportLayout
    updated_at: float
    updated_by: str | None


class ReportLayoutRepository(ABC):
    @abstractmethod
    def get(self) -> SavedLayout | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, saved: SavedLayout) -> None:
        raise NotImplementedError


class InMemoryReportLayoutRepository(ReportLayoutRepository):
    def __init__(self) -> None:
        self._saved: SavedLayout | None = None

    def get(self) -> SavedLayout | None:
        return self._saved

    def save(self, saved: SavedLayout) -> None:
        self._saved = saved


def layout_from_stored(stored: dict) -> ReportLayout:
    """A layout as it was stored. Sections and columns that no longer
    exist are dropped, so an old layout never stops a report."""
    sections = tuple(s for s in stored.get("sections", ()) if s in SECTIONS)
    columns = tuple(c for c in stored.get("columns", ()) if c in COLUMNS)
    return ReportLayout(
        company_name=str(stored.get("company_name") or ""),
        title=str(stored.get("title") or DEFAULT_TITLE),
        sections=sections or DEFAULT_LAYOUT.sections,
        columns=columns or DEFAULT_LAYOUT.columns,
    )


def layout_to_stored(layout: ReportLayout) -> dict:
    return {
        "company_name": layout.company_name,
        "title": layout.title,
        "sections": list(layout.sections),
        "columns": list(layout.columns),
    }


class ReportLayoutService:
    def __init__(
        self,
        repository: ReportLayoutRepository,
        cache_seconds: float = 30.0,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """cache_seconds: how long an export goes without looking the
        layout up again (another server's change is seen after that)."""
        self._repository = repository
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._monotonic = monotonic
        self._cached: tuple[float, SavedLayout | None] | None = None

    def saved(self) -> SavedLayout | None:
        """What an administrator saved; None while the built-in layout is in use."""
        now = self._monotonic()
        if self._cached is None or now - self._cached[0] >= self._cache_seconds:
            self._cached = (now, self._repository.get())
        return self._cached[1]

    def layout(self) -> ReportLayout:
        saved = self.saved()
        return DEFAULT_LAYOUT if saved is None else saved.layout

    def save(
        self,
        company_name: str,
        title: str,
        sections: list[str],
        columns: list[str],
        by: str | None,
    ) -> SavedLayout:
        saved = SavedLayout(validated(company_name, title, sections, columns), self._clock(), by)
        self._repository.save(saved)
        self._cached = (self._monotonic(), saved)
        return saved
