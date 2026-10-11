"""Writing log entries off the thread that produced them.

The audit log and the AI log are written while a request is answered or a
live call is analysed. Neither may wait for the database, so entries are
queued here and stored by one background thread, in order and in batches.
When the database cannot keep up the queue fills and new entries are
dropped (and counted) rather than holding anything up.
"""

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Generic, TypeVar

from app.observability.metrics import LOG_ENTRIES_DROPPED

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BackgroundWriter(Generic[T]):
    def __init__(
        self,
        write: Callable[[list[T]], None],
        name: str,
        max_pending: int = 10_000,
        batch_size: int = 100,
    ) -> None:
        """write: stores a batch, in the order given. name: what the
        thread and the dropped-entries count are called."""
        self._write = write
        self._name = name
        self._batch_size = max(1, batch_size)
        self._queue: queue.Queue[T] = queue.Queue(maxsize=max_pending)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def put(self, item: T) -> bool:
        """Queue the item. False when the queue is full and it was dropped."""
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            LOG_ENTRIES_DROPPED.inc(self._name)
            return False
        self._ensure_started()
        return True

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until everything queued so far has been written (or
        dropped by a failing write). False when that took longer than
        timeout."""
        deadline = time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def _ensure_started(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name=f"log-writer-{self._name}", daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        while True:
            batch = [self._queue.get()]
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self._write(batch)
            except Exception:
                # The entries are lost: keeping them would only fill the
                # queue while the database is down.
                LOG_ENTRIES_DROPPED.inc(self._name, amount=len(batch))
                logger.exception("Could not write %d %s entries", len(batch), self._name)
            finally:
                for _ in batch:
                    self._queue.task_done()
