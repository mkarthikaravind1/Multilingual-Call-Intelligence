from dataclasses import dataclass

from app.core.constants import COMPLAINT_CATEGORIES

# The catch-all category; complaint detection lists it last.
OTHER_CATEGORY = "Other"
# Accepted emerging themes become categories with names up to this long.
MAX_CUSTOM_CATEGORY_NAME_LENGTH = 40
# Any stored category name (built-in or custom) fits in this.
_MAX_CATEGORY_NAME_LENGTH = 100


def require_category_name(value: object, field_name: str = "category") -> None:
    """Shape check for a complaint category stored on a record.

    Records accept any category name: besides the built-in
    COMPLAINT_CATEGORIES, supervisors add categories by accepting emerging
    themes, and a call keeps its category even after the theme is later
    rejected. Which categories may be *detected* is decided where results
    come in (ComplaintCategoryCatalog), not here.
    """
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > _MAX_CATEGORY_NAME_LENGTH
    ):
        raise ValueError(f"Unsupported complaint {field_name}: {value!r}.")


def is_built_in_category(name: str) -> bool:
    return name in COMPLAINT_CATEGORIES


@dataclass(frozen=True)
class ComplaintCategory:
    """A category complaint detection can report: one of the built-in
    COMPLAINT_CATEGORIES, or a theme a supervisor accepted (custom)."""

    name: str
    # What counts as this category; told to the detector. None for built-ins.
    description: str | None = None
    # The accepted emerging-complaint candidate it came from (custom only).
    candidate_id: str | None = None

    def __post_init__(self) -> None:
        require_category_name(self.name)
        if self.candidate_id is None and not is_built_in_category(self.name):
            raise ValueError(f"{self.name!r} is not a built-in category; give its candidate_id.")

    @property
    def built_in(self) -> bool:
        return self.candidate_id is None


BUILT_IN_CATEGORIES: tuple[ComplaintCategory, ...] = tuple(
    ComplaintCategory(name) for name in COMPLAINT_CATEGORIES
)
