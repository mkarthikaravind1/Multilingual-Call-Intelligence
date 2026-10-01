import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeriodicJob:
    name: str
    interval_seconds: float
    run: Callable[[], object]


class BackgroundJobRunner:
    """Runs each job on its own daemon thread every interval_seconds, from
    application startup until shutdown. A failing run is logged and the job
    carries on at its next interval."""

    def __init__(self, jobs: list[PeriodicJob] | None = None) -> None:
        self._jobs = [job for job in (jobs or []) if job.interval_seconds > 0]
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def job_names(self) -> tuple[str, ...]:
        return tuple(job.name for job in self._jobs)

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for job in self._jobs:
            thread = threading.Thread(
                target=self._loop, args=(job,), name=f"job-{job.name}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
            logger.info("Started background job %r every %.0fs", job.name, job.interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout)
        self._threads = []

    def _loop(self, job: PeriodicJob) -> None:
        # The first run waits one interval so startup stays quick.
        while not self._stop.wait(job.interval_seconds):
            try:
                job.run()
            except Exception:
                logger.exception("Background job %r failed", job.name)
