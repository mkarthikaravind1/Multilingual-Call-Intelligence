import logging
import threading
import time
from collections.abc import Callable, Iterable

from app.domain.complaint_category import (
    BUILT_IN_CATEGORIES,
    OTHER_CATEGORY,
    ComplaintCategory,
)
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewStatus,
)
from app.services.emerging_complaint_repository import EmergingComplaintRepository

logger = logging.getLogger(__name__)


def custom_category_of(candidate: EmergingComplaintCandidate) -> ComplaintCategory | None:
    """The category an accepted theme adds, or None if it adds none."""
    if candidate.status is not EmergingComplaintReviewStatus.ACCEPTED or not candidate.category_name:
        return None
    return ComplaintCategory(
        name=candidate.category_name,
        description=candidate.category_description or candidate.description,
        candidate_id=candidate.candidate_id,
    )


def _ordered(custom: Iterable[ComplaintCategory]) -> tuple[ComplaintCategory, ...]:
    # "Other" stays last: the detector should use it only when nothing fits.
    built_in = [c for c in BUILT_IN_CATEGORIES if c.name != OTHER_CATEGORY]
    other = [c for c in BUILT_IN_CATEGORIES if c.name == OTHER_CATEGORY]
    return (*built_in, *sorted(custom, key=lambda c: c.name.casefold()), *other)


class ComplaintCategoryCatalog:
    """The complaint categories detection can report: the built-in
    COMPLAINT_CATEGORIES plus every emerging theme a supervisor accepted.

    Accepted themes are read from the emerging-complaint repository and
    cached for cache_seconds, so every API instance picks up a newly
    accepted category within that time (invalidate() refreshes this
    instance at once). Without a repository it holds the built-ins only.
    If the repository cannot be read, the last categories read are kept.
    """

    def __init__(
        self,
        repository: EmergingComplaintRepository | None = None,
        cache_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository
        self._cache_seconds = max(0.0, cache_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._categories: tuple[ComplaintCategory, ...] = _ordered(())
        self._loaded_at: float | None = None

    def categories(self) -> tuple[ComplaintCategory, ...]:
        """Built-ins, then custom categories by name, then "Other"."""
        if self._repository is None:
            return self._categories
        with self._lock:
            now = self._clock()
            if self._loaded_at is None or now - self._loaded_at >= self._cache_seconds:
                self._loaded_at = now
                try:
                    self._categories = _ordered(self._read_custom())
                except Exception:
                    logger.exception(
                        "Could not read accepted complaint themes; keeping the last categories"
                    )
            return self._categories

    def names(self) -> tuple[str, ...]:
        return tuple(category.name for category in self.categories())

    def custom(self) -> tuple[ComplaintCategory, ...]:
        return tuple(category for category in self.categories() if not category.built_in)

    def is_known(self, name: str) -> bool:
        return name in self.names()

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = None

    def conflicting_name(self, name: str, candidate_id: str | None = None) -> str | None:
        """The existing category that name clashes with (ignoring case),
        if any; candidate_id's own category does not count. Reads the
        repository directly, not the cache."""
        wanted = name.strip().casefold()
        custom = self._read_custom() if self._repository is not None else ()
        for category in (*BUILT_IN_CATEGORIES, *custom):
            if candidate_id is not None and category.candidate_id == candidate_id:
                continue
            if category.name.casefold() == wanted:
                return category.name
        return None

    def _read_custom(self) -> tuple[ComplaintCategory, ...]:
        accepted = self._repository.list_by_status((EmergingComplaintReviewStatus.ACCEPTED,))
        return tuple(
            category
            for category in (custom_category_of(candidate) for candidate in accepted)
            if category is not None
        )


# Built-in categories only: the default wherever no catalog is passed in.
BUILT_IN_CATALOG = ComplaintCategoryCatalog()
