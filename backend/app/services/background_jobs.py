import logging
import threading
import time
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

    def __init__(
        self,
        jobs: list[PeriodicJob] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._jobs = [job for job in (jobs or []) if job.interval_seconds > 0]
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._clock = clock
        # job name -> when its last run ended (or, before its first run,
        # when it was started). A job that hangs stops moving this.
        self._last_run_at: dict[str, float] = {}

    @property
    def job_names(self) -> tuple[str, ...]:
        return tuple(job.name for job in self._jobs)

    def overdue_by(self) -> dict[str, float]:
        """For each started job: the time since its last run ended, in
        intervals. About 1 when all is well; it keeps growing when a
        job hangs or its thread died."""
        now = self._clock()
        return {
            job.name: (now - self._last_run_at[job.name]) / job.interval_seconds
            for job in self._jobs
            if job.name in self._last_run_at
        }

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for job in self._jobs:
            self._last_run_at[job.name] = self._clock()
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
            self._last_run_at[job.name] = self._clock()
