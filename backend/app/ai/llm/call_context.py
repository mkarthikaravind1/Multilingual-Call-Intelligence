"""Which call the AI is working on, so its requests can be logged against it.

The code that starts work for a call (a live analysis, the post-call
processing, the speaker-role check) says so here; the logged LLM client
reads it for every request made underneath, on the same thread.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_call_id: ContextVar[str | None] = ContextVar("ai_call_id", default=None)


@contextmanager
def working_on_call(call_id: str | None) -> Iterator[None]:
    token = _call_id.set(call_id)
    try:
        yield
    finally:
        _call_id.reset(token)


def current_call_id() -> str | None:
    return _call_id.get()
