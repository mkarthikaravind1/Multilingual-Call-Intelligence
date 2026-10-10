import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from app.domain.complaint_category import (
    BUILT_IN_CATEGORIES,
    OTHER_CATEGORY,
    ComplaintCategory,
)
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewStatus,
)
from app.domain.managed_category import (
    ADMIN_PREFIX,
    ManagedCategory,
    ManagedCategoryRepository,
    built_in_key,
    theme_key,
)
from app.services.emerging_complaint_repository import EmergingComplaintRepository

logger = logging.getLogger(__name__)

CategorySource = Literal["built_in", "theme", "admin"]


def custom_category_of(candidate: EmergingComplaintCandidate) -> ComplaintCategory | None:
    """The category an accepted theme adds, or None if it adds none."""
    if candidate.status is not EmergingComplaintReviewStatus.ACCEPTED or not candidate.category_name:
        return None
    return ComplaintCategory(
        name=candidate.category_name,
        description=candidate.category_description or candidate.description,
        candidate_id=candidate.candidate_id,
    )


@dataclass(frozen=True)
class CatalogEntry:
    """A category with what an administrator has decided about it."""

    # builtin:<name>, theme:<candidate id> or admin:<id> (see ManagedCategory).
    key: str
    category: ComplaintCategory
    source: CategorySource
    # Names it had before: complaints stored under them count under its
    # name now.
    former_names: tuple[str, ...] = ()
    # When it was retired; None: detection reports it.
    retired_at: float | None = None

    @property
    def is_retired(self) -> bool:
        return self.retired_at is not None


def _ordered(entries: Iterable[CatalogEntry]) -> tuple[CatalogEntry, ...]:
    # "Other" stays last: the detector should use it only when nothing fits.
    entries = list(entries)
    built_in = [e for e in entries if e.source == "built_in" and e.category.name != OTHER_CATEGORY]
    other = [e for e in entries if e.source == "built_in" and e.category.name == OTHER_CATEGORY]
    custom = sorted(
        (e for e in entries if e.source != "built_in"), key=lambda e: e.category.name.casefold()
    )
    return (*built_in, *custom, *other)


def _built_in_entries(managed: dict[str, ManagedCategory]) -> list[CatalogEntry]:
    entries = []
    for category in BUILT_IN_CATEGORIES:
        decided = managed.get(built_in_key(category.name))
        entries.append(
            CatalogEntry(
                key=built_in_key(category.name),
                category=category,
                source="built_in",
                retired_at=None if decided is None else decided.retired_at,
            )
        )
    return entries


class ComplaintCategoryCatalog:
    """The complaint categories: the built-in COMPLAINT_CATEGORIES, every
    emerging theme a supervisor accepted, and those an administrator
    added; less the ones an administrator retired, and under the names
    they gave them.

    categories() are the ones detection can report now. current_name()
    takes a name a category had before to the one it has now, so stored
    complaints follow a rename without being rewritten.

    Themes and the administrator's decisions are read from their
    repositories and cached for cache_seconds, so every API instance picks
    up a change within that time (invalidate() refreshes this instance at
    once). Without repositories it holds the built-ins only. If a
    repository cannot be read, the last categories read are kept.

    Only one caller re-reads at a time, and other callers do not wait for
    it: they get the last categories read. Live detection never queues
    behind a slow database, except for the very first read.
    """

    def __init__(
        self,
        repository: EmergingComplaintRepository | None = None,
        cache_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        managed: ManagedCategoryRepository | None = None,
    ) -> None:
        self._repository = repository
        self._managed = managed
        self._cache_seconds = max(0.0, cache_seconds)
        self._clock = clock
        # Held only by the caller re-reading the repositories.
        self._refresh_lock = threading.Lock()
        self._entries: tuple[CatalogEntry, ...] = ()
        self._categories: tuple[ComplaintCategory, ...] = ()
        self._current_names: dict[str, str] = {}
        self._hold(_ordered(_built_in_entries({})))
        self._loaded_at: float | None = None
        self._has_read = False

    def categories(self) -> tuple[ComplaintCategory, ...]:
        """The categories in use: built-ins, then custom categories by
        name, then "Other"."""
        self._refresh_if_stale()
        return self._categories

    def entries(self) -> tuple[CatalogEntry, ...]:
        """Every category, retired ones included, in the same order."""
        self._refresh_if_stale()
        return self._entries

    def names(self) -> tuple[str, ...]:
        return tuple(category.name for category in self.categories())

    def custom(self) -> tuple[ComplaintCategory, ...]:
        return tuple(category for category in self.categories() if not category.built_in)

    def is_known(self, name: str) -> bool:
        return name in self.names()

    def current_name(self, name: str) -> str:
        """The name the category stored as `name` has now: `name` itself
        unless it was renamed since."""
        self._refresh_if_stale()
        return self._current_names.get(name.casefold(), name)

    def stored_names(self, name: str) -> tuple[str, ...]:
        """Every name complaints of the category called `name` now may be
        stored under: `name` and the names it had before."""
        self._refresh_if_stale()
        for entry in self._entries:
            if entry.category.name.casefold() == name.casefold():
                return (entry.category.name, *entry.former_names)
        return (name,)

    def invalidate(self) -> None:
        # A re-read already under way stamped its start time before this,
        # so the next call reads again and sees the change.
        self._loaded_at = None

    def read_entries(self) -> tuple[CatalogEntry, ...]:
        """Every category as the repositories hold them now, not the cache
        (for deciding a change; raises when they cannot be read)."""
        return _ordered(self._read())

    def conflicting_name(
        self, name: str, candidate_id: str | None = None, key: str | None = None
    ) -> str | None:
        """The existing category that name clashes with (ignoring case):
        one that has it now, or had it before, so old complaints are never
        counted under another category. candidate_id's (or key's) own
        category does not count. Reads the repositories, not the cache."""
        wanted = name.strip().casefold()
        own = key if key is not None else (None if candidate_id is None else theme_key(candidate_id))
        for entry in self.read_entries():
            if entry.key == own:
                continue
            if wanted in {n.casefold() for n in (entry.category.name, *entry.former_names)}:
                return entry.category.name
        return None

    def _refresh_if_stale(self) -> None:
        if (self._repository is None and self._managed is None) or not self._is_stale():
            return
        # Until the first read succeeds the cached list has the built-ins
        # only, so wait for it; afterwards serve the last list.
        if not self._refresh_lock.acquire(blocking=not self._has_read):
            return
        try:
            if self._is_stale():
                self._refresh()
        finally:
            self._refresh_lock.release()

    def _is_stale(self) -> bool:
        loaded_at = self._loaded_at
        return loaded_at is None or self._clock() - loaded_at >= self._cache_seconds

    def _refresh(self) -> None:
        # Stamped first, so a failing repository is retried once per
        # cache_seconds rather than on every call.
        self._loaded_at = self._clock()
        try:
            self._hold(_ordered(self._read()))
            self._has_read = True
        except Exception:
            logger.exception("Could not read the complaint categories; keeping the last ones")

    def _hold(self, entries: tuple[CatalogEntry, ...]) -> None:
        current_names = {
            former.casefold(): entry.category.name
            for entry in entries
            for former in entry.former_names
        }
        # Swapped whole, so a reader never sees half of a change.
        self._entries = entries
        self._categories = tuple(e.category for e in entries if not e.is_retired)
        self._current_names = current_names

    def _read(self) -> list[CatalogEntry]:
        managed = (
            {} if self._managed is None else {m.key: m for m in self._managed.list_all()}
        )
        entries = _built_in_entries(managed)
        for theme in self._read_custom():
            # A theme an administrator renamed or retired.
            decided = managed.get(theme_key(theme.candidate_id))
            entries.append(
                CatalogEntry(
                    key=theme_key(theme.candidate_id),
                    category=theme
                    if decided is None
                    else ComplaintCategory(
                        name=decided.name,
                        description=decided.description or theme.description,
                        candidate_id=theme.candidate_id,
                    ),
                    source="theme",
                    former_names=() if decided is None else decided.former_names,
                    retired_at=None if decided is None else decided.retired_at,
                )
            )
        for decided in managed.values():
            if decided.key.startswith(ADMIN_PREFIX):
                entries.append(
                    CatalogEntry(
                        key=decided.key,
                        category=ComplaintCategory(
                            name=decided.name,
                            description=decided.description,
                            category_key=decided.key,
                        ),
                        source="admin",
                        former_names=decided.former_names,
                        retired_at=decided.retired_at,
                    )
                )
        return entries

    def _read_custom(self) -> tuple[ComplaintCategory, ...]:
        if self._repository is None:
            return ()
        accepted = self._repository.list_by_status((EmergingComplaintReviewStatus.ACCEPTED,))
        return tuple(
            category
            for category in (custom_category_of(candidate) for candidate in accepted)
            if category is not None
        )


# Built-in categories only: the default wherever no catalog is passed in.
BUILT_IN_CATALOG = ComplaintCategoryCatalog()
