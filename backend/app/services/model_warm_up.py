"""Loading the slow speech models when the server starts.

The speaker-separation model takes the better part of a minute to load.
It is loaded in the background at startup so that the first call does not
wait for it; a call that arrives sooner has its audio queued until the
model is ready. Whoever must not give up on that audio too early (the end
of a call waiting for its last speech, see TelephonyCallService) asks here
whether loading is still going on.
"""

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ModelWarmUp:
    def __init__(self, load: Callable[[], object]) -> None:
        self._load = load
        self._started = threading.Event()
        self._finished = threading.Event()

    @property
    def in_progress(self) -> bool:
        return self._started.is_set() and not self._finished.is_set()

    def run(self) -> None:
        """Load the models (a failure is logged: they then load on first use)."""
        self._started.set()
        try:
            self._load()
        except Exception as exc:
            logger.warning("Speech models could not be preloaded: %s", exc)
        finally:
            self._finished.set()
