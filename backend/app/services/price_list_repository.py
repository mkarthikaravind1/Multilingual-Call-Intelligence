import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

from app.estimation.price_list import PriceListRow, PriceListSettings

# Older versions beyond this many are deleted when a new one is saved.
KEPT_VERSIONS = 30


@dataclass(frozen=True)
class PriceListVersionInfo:
    version_id: int
    created_at: float
    created_by: str | None
    # "upload", "edit" or "restore".
    source: str
    note: str | None
    row_count: int
    is_active: bool


@dataclass(frozen=True)
class PriceListVersion:
    info: PriceListVersionInfo
    settings: PriceListSettings
    rows: tuple[PriceListRow, ...]


class PriceListRepository(ABC):
    """Every saved version of the price list; the newest is the one in use.
    Versions are never changed, so any of them can be restored."""

    @abstractmethod
    def get_active(self) -> PriceListVersion | None:
        raise NotImplementedError

    @abstractmethod
    def get(self, version_id: int) -> PriceListVersion | None:
        raise NotImplementedError

    @abstractmethod
    def add(
        self,
        settings: PriceListSettings,
        rows: tuple[PriceListRow, ...],
        *,
        created_at: float,
        created_by: str | None,
        source: str,
        note: str | None = None,
    ) -> PriceListVersion:
        """Store a new version and make it the active one."""
        raise NotImplementedError

    @abstractmethod
    def list_versions(self, limit: int = KEPT_VERSIONS) -> tuple[PriceListVersionInfo, ...]:
        """Newest first."""
        raise NotImplementedError


class InMemoryPriceListRepository(PriceListRepository):
    def __init__(self) -> None:
        self._versions: list[PriceListVersion] = []
        self._next_id = 1
        self._lock = threading.Lock()

    def get_active(self) -> PriceListVersion | None:
        return self._versions[-1] if self._versions else None

    def get(self, version_id: int) -> PriceListVersion | None:
        return next((v for v in self._versions if v.info.version_id == version_id), None)

    def add(self, settings, rows, *, created_at, created_by, source, note=None):
        with self._lock:
            version = PriceListVersion(
                PriceListVersionInfo(
                    version_id=self._next_id,
                    created_at=created_at,
                    created_by=created_by,
                    source=source,
                    note=note,
                    row_count=len(rows),
                    is_active=True,
                ),
                settings,
                tuple(rows),
            )
            self._next_id += 1
            self._versions = [
                PriceListVersion(_inactive(v.info), v.settings, v.rows) for v in self._versions
            ][-(KEPT_VERSIONS - 1) :] + [version]
            return version

    def list_versions(self, limit: int = KEPT_VERSIONS) -> tuple[PriceListVersionInfo, ...]:
        return tuple(v.info for v in reversed(self._versions))[:limit]


def _inactive(info: PriceListVersionInfo) -> PriceListVersionInfo:
    return replace(info, is_active=False)
