"""What an administrator has decided about a complaint category: one they
added, or a change (a new name, retirement) to one that exists anyway."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.complaint_category import require_category_name

# The keys of the three kinds of category.
BUILT_IN_PREFIX = "builtin:"
THEME_PREFIX = "theme:"
ADMIN_PREFIX = "admin:"


def built_in_key(name: str) -> str:
    return f"{BUILT_IN_PREFIX}{name}"


def theme_key(candidate_id: str) -> str:
    return f"{THEME_PREFIX}{candidate_id}"


@dataclass(frozen=True)
class ManagedCategory:
    # builtin:<name>, theme:<the accepted candidate's id> or admin:<id>.
    key: str
    # The category's name now.
    name: str
    # What counts as it, told to the detector; None: nothing beyond what
    # the category has anyway (built-ins: none; themes: the theme's own).
    description: str | None = None
    # Names it had before, oldest first: complaints stored under them are
    # shown and counted under the name it has now.
    former_names: tuple[str, ...] = ()
    # When it was retired (detection no longer reports it); None: in use.
    retired_at: float | None = None
    updated_at: float = 0.0
    updated_by: str | None = None

    def __post_init__(self) -> None:
        if not self.key.startswith((BUILT_IN_PREFIX, THEME_PREFIX, ADMIN_PREFIX)):
            raise ValueError(f"Unsupported category key: {self.key!r}.")
        require_category_name(self.name)
        for name in self.former_names:
            require_category_name(name, "former name")

    @property
    def is_retired(self) -> bool:
        return self.retired_at is not None


class ManagedCategoryRepository(ABC):
    @abstractmethod
    def save(self, category: ManagedCategory) -> None:
        """Insert it, or replace the one with its key."""
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str) -> ManagedCategory | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[ManagedCategory, ...]:
        raise NotImplementedError


class InMemoryManagedCategoryRepository(ManagedCategoryRepository):
    def __init__(self) -> None:
        self._by_key: dict[str, ManagedCategory] = {}

    def save(self, category: ManagedCategory) -> None:
        self._by_key[category.key] = category

    def get(self, key: str) -> ManagedCategory | None:
        return self._by_key.get(key)

    def list_all(self) -> tuple[ManagedCategory, ...]:
        return tuple(self._by_key.values())
