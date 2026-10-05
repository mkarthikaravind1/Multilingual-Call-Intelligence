"""Keeps the AI analysis of live phone calls off the speech path.

The telephony pipeline turns each audio chunk into an utterance, in order,
one chunk at a time. If every utterance also waited for the LLM analysis
(complaints, sentiment, next question, escalation: several seconds, more
when the provider rate-limits), speech would fall further and further
behind the call. Instead each utterance is stored and shown at once, and the
analysis runs here, per call, in the background:

- at most one analysis runs per call at a time;
- utterances that arrive while it runs are covered by a single follow-up
  analysis of the whole conversation (analysis always reads the full call),
  so a burst of speech costs one round of LLM calls, not one per utterance.
"""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Protocol

from app.domain.utterance import Utterance
from app.services.call_workflow_service import CallAnalysisResult

logger = logging.getLogger(__name__)


class DeferredAnalysisWorkflow(Protocol):
    def record_utterance(self, call_id: str, utterance: Utterance) -> None: ...

    def record_utterance_update(self, call_id: str, utterance: Utterance) -> None: ...

    def analyze_latest_speech(self, call_id: str) -> CallAnalysisResult | None: ...

    def analyze_call(self, call_id: str) -> CallAnalysisResult: ...


class LiveAnalysisScheduler:
    """An UtteranceProcessor for live audio: records utterances immediately
    and schedules coalesced background analysis."""

    def __init__(
        self,
        workflow: DeferredAnalysisWorkflow,
        executor: Executor | None = None,
        max_workers: int = 4,
        min_interval_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._workflow = workflow
        # A follow-up analysis starts no sooner than this after the previous
        # one started: each run makes several (rate-limited) LLM calls.
        self._min_interval = max(0.0, min_interval_seconds)
        self._sleep = sleep
        # call_id -> when its latest analysis started.
        self._last_start: dict[str, float] = {}
        self._executor = executor
        self._max_workers = max_workers
        self._lock = threading.Lock()
        # call_id -> whether more speech arrived since its running analysis started.
        self._running: dict[str, bool] = {}
        self._idle = threading.Condition(self._lock)

    def process_utterance(self, call_id: str, utterance: Utterance) -> CallAnalysisResult:
        self._workflow.record_utterance(call_id, utterance)
        self.request_analysis(call_id)
        # What is known right now; the new analysis follows in the background.
        return self._workflow.analyze_call(call_id)

    def process_utterance_update(self, call_id: str, utterance: Utterance) -> CallAnalysisResult:
        """The latest utterance grew (same utterance_id): store it at once
        and re-analyse in the background, as for a new utterance."""
        self._workflow.record_utterance_update(call_id, utterance)
        self.request_analysis(call_id)
        return self._workflow.analyze_call(call_id)

    def request_analysis(self, call_id: str) -> None:
        with self._lock:
            if call_id in self._running:
                self._running[call_id] = True
                return
            self._running[call_id] = False
        self._submit(lambda: self._run(call_id))

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until no analysis is running or waiting (tests, shutdown)."""
        with self._idle:
            return self._idle.wait_for(lambda: not self._running, timeout)

    def _run(self, call_id: str) -> None:
        while True:
            wait = self._min_interval - (time.monotonic() - self._last_start.get(call_id, -1e9))
            if wait > 0:
                self._sleep(wait)
            self._last_start[call_id] = time.monotonic()
            try:
                self._workflow.analyze_latest_speech(call_id)
            except Exception:
                logger.exception("Live analysis failed for call %r", call_id)
            with self._lock:
                if self._running.get(call_id):
                    self._running[call_id] = False  # analyse the newer speech
                    continue
                self._running.pop(call_id, None)
                self._idle.notify_all()
                return

    def _submit(self, work: Callable[[], None]) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="live-analysis"
            )
        self._executor.submit(work)
