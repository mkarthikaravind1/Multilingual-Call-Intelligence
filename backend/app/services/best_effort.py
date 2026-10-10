import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def best_effort(what: str, call_id: str, action: Callable[..., _T], *args) -> _T | None:
    """action(*args), for a step the call's processing must not stop for
    (lifecycle, escalation, delivery, estimate...): a failure is logged
    and gives None."""
    try:
        return action(*args)
    except Exception:
        logger.exception("%s failed for call %r", what, call_id)
        return None
