"""The id every call is given: "CALL-" and a running number, one counter
for every kind of call (phone, test audio, started by hand), so an id can
be read out and searched for."""

import re
import threading
from abc import ABC, abstractmethod

CALL_ID_PREFIX = "CALL-"
# Shorter numbers are padded to this width; longer ones are written in full.
CALL_NUMBER_DIGITS = 6
_CALL_ID = re.compile(rf"^{CALL_ID_PREFIX}(\d+)$")


def format_call_id(number: int) -> str:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("A call number is a whole number from 1.")
    return f"{CALL_ID_PREFIX}{number:0{CALL_NUMBER_DIGITS}d}"


def call_number(call_id: str) -> int | None:
    """The number in a call id of this form; None for any other id."""
    match = _CALL_ID.match(call_id)
    return None if match is None else int(match.group(1))


class CallNumbers(ABC):
    """Hands out call numbers. Never the same one twice, on any instance."""

    @abstractmethod
    def next(self) -> int:
        raise NotImplementedError


class InMemoryCallNumbers(CallNumbers):
    """For one process (tests, or running without a database)."""

    def __init__(self, last: int = 0) -> None:
        self._last = last
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._last += 1
            return self._last
