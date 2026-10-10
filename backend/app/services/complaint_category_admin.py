"""An administrator's changes to the complaint categories: adding one,
renaming one, retiring one and bringing it back.

Detection picks a change up through the ComplaintCategoryCatalog (at once
on this instance, within its cache time on the others). Stored complaints
are never rewritten: a renamed category keeps its former names, and what
was stored under them is shown and counted under the name it has now.
"""

import dataclasses
import time
import uuid
from collections.abc import Callable

from app.domain.complaint_category import (
    MAX_CUSTOM_CATEGORY_NAME_LENGTH,
    OTHER_CATEGORY,
)
from app.domain.managed_category import (
    ADMIN_PREFIX,
    ManagedCategory,
    ManagedCategoryRepository,
)
from app.services.complaint_category_catalog import CatalogEntry, ComplaintCategoryCatalog

MAX_CATEGORY_DESCRIPTION_LENGTH = 500


class CategoryAdminError(ValueError):
    """A change that cannot be made as asked (the message says why)."""


class CategoryNotFoundError(Exception):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"There is no complaint category {key!r}.")


class ComplaintCategoryAdminService:
    def __init__(
        self,
        catalog: ComplaintCategoryCatalog,
        repository: ManagedCategoryRepository,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._clock = clock

    def list_categories(self) -> tuple[CatalogEntry, ...]:
        """Every category, retired ones included, as stored now."""
        return self._catalog.read_entries()

    def add(self, name: str, description: str | None, by: str) -> CatalogEntry:
        name = self._free_name(name)
        key = f"{ADMIN_PREFIX}{uuid.uuid4().hex}"
        self._repository.save(
            ManagedCategory(
                key=key,
                name=name,
                description=_description(description),
                updated_at=self._clock(),
                updated_by=by,
            )
        )
        return self._changed(key)

    def rename(self, key: str, name: str, by: str) -> CatalogEntry:
        entry = self._entry(key)
        if entry.source == "built_in":
            raise CategoryAdminError(
                f"{entry.category.name} is a built-in category and cannot be renamed. "
                "Retire it and add a new one instead."
            )
        name = self._free_name(name, key)
        old = entry.category.name
        if name == old:
            return entry
        # A name it goes back to is no longer a former one.
        former = tuple(
            n for n in (*entry.former_names, old) if n.casefold() != name.casefold()
        )
        self._save(entry, by, name=name, former_names=former)
        return self._changed(key)

    def describe(self, key: str, description: str | None, by: str) -> CatalogEntry:
        entry = self._entry(key)
        if entry.source == "built_in":
            raise CategoryAdminError(
                f"{entry.category.name} is a built-in category and has no description to change."
            )
        self._save(entry, by, description=_description(description))
        return self._changed(key)

    def retire(self, key: str, by: str) -> CatalogEntry:
        entry = self._entry(key)
        if entry.category.name == OTHER_CATEGORY and entry.source == "built_in":
            raise CategoryAdminError(
                f'"{OTHER_CATEGORY}" cannot be retired: a complaint that fits no other '
                "category needs somewhere to go."
            )
        if not entry.is_retired:
            self._save(entry, by, retired_at=self._clock())
        return self._changed(key)

    def restore(self, key: str, by: str) -> CatalogEntry:
        entry = self._entry(key)
        if entry.is_retired:
            self._save(entry, by, retired_at=None)
        return self._changed(key)

    def _entry(self, key: str) -> CatalogEntry:
        for entry in self._catalog.read_entries():
            if entry.key == key:
                return entry
        raise CategoryNotFoundError(key)

    def _free_name(self, name: str, key: str | None = None) -> str:
        name = " ".join((name or "").split())
        if not name:
            raise CategoryAdminError("A category needs a name.")
        if len(name) > MAX_CUSTOM_CATEGORY_NAME_LENGTH:
            raise CategoryAdminError(
                f"A category name has at most {MAX_CUSTOM_CATEGORY_NAME_LENGTH} characters."
            )
        clash = self._catalog.conflicting_name(name, key=key)
        if clash is not None:
            raise CategoryAdminError(
                f'"{name}" is taken: the category "{clash}" has, or once had, that name.'
            )
        return name

    def _save(self, entry: CatalogEntry, by: str, **changes) -> None:
        """Store the entry as decided so far, with these changes."""
        stored = self._repository.get(entry.key) or ManagedCategory(
            key=entry.key,
            name=entry.category.name,
            former_names=entry.former_names,
            retired_at=entry.retired_at,
        )
        self._repository.save(
            dataclasses.replace(stored, updated_at=self._clock(), updated_by=by, **changes)
        )

    def _changed(self, key: str) -> CatalogEntry:
        self._catalog.invalidate()
        return self._entry(key)


def _description(description: str | None) -> str | None:
    text = " ".join((description or "").split())
    if len(text) > MAX_CATEGORY_DESCRIPTION_LENGTH:
        raise CategoryAdminError(
            f"A description has at most {MAX_CATEGORY_DESCRIPTION_LENGTH} characters."
        )
    return text or None
