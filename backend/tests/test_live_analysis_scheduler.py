"""Live audio: speech is stored at once, AI analysis follows in the
background, coalesced per call."""

from concurrent.futures import Executor, Future

from app.services.live_analysis_scheduler import LiveAnalysisScheduler
from tests.test_live_analysis_store import CALL_ID, _cluster, _SENTIMENT, _utterance
from app.services.live_state_store import InMemoryLiveStateStore


class QueueExecutor(Executor):
    """Runs submitted work only when the test says so."""

    def __init__(self) -> None:
        self.queued = []

    def submit(self, fn, *args, **kwargs):
        self.queued.append((fn, args, kwargs))
        return Future()

    def run_all(self) -> None:
        while self.queued:
            fn, args, kwargs = self.queued.pop(0)
            fn(*args, **kwargs)


class CountingWorkflow:
    def __init__(self, inner, on_analyze=None) -> None:
        self.inner = inner
        self.analyses = 0
        self.on_analyze = on_analyze

    def record_utterance(self, call_id, utterance):
        self.inner.record_utterance(call_id, utterance)

    def analyze_latest_speech(self, call_id):
        self.analyses += 1
        if self.on_analyze is not None:
            self.on_analyze()
        return self.inner.analyze_latest_speech(call_id)

    def analyze_call(self, call_id):
        return self.inner.analyze_call(call_id)


def test_utterance_is_stored_and_visible_before_analysis_runs():
    cluster = _cluster(InMemoryLiveStateStore())
    executor = QueueExecutor()
    scheduler = LiveAnalysisScheduler(cluster.a, executor=executor)
    before = cluster.a.live_revision(CALL_ID)

    scheduler.process_utterance(CALL_ID, _utterance())

    # Transcript stored and live views told, while no LLM has run yet.
    assert cluster.call_service.get_call(CALL_ID).utterance_count == 1
    assert cluster.a.live_revision(CALL_ID) not in (None, before)
    assert cluster.b.analyze_call(CALL_ID).sentiment is None

    executor.run_all()
    assert cluster.b.analyze_call(CALL_ID).sentiment == _SENTIMENT


def test_speech_during_an_analysis_is_covered_by_one_follow_up():
    cluster = _cluster(InMemoryLiveStateStore())
    executor = QueueExecutor()
    holder = {}

    def more_speech_arrives():
        if workflow.analyses == 1:
            for index in (1, 2, 3):
                holder["scheduler"].process_utterance(CALL_ID, _utterance(index))

    workflow = CountingWorkflow(cluster.a, on_analyze=more_speech_arrives)
    scheduler = holder["scheduler"] = LiveAnalysisScheduler(workflow, executor=executor)

    scheduler.process_utterance(CALL_ID, _utterance(0))
    executor.run_all()

    # One analysis for the first utterance, one for the three that came during it.
    assert workflow.analyses == 2
    assert len(executor.queued) == 0
    assert scheduler.wait_until_idle(timeout=0)


def test_calls_are_analysed_independently():
    cluster = _cluster(InMemoryLiveStateStore())
    cluster.call_service.start_call("call-2")
    executor = QueueExecutor()
    workflow = CountingWorkflow(cluster.a)
    scheduler = LiveAnalysisScheduler(workflow, executor=executor)

    scheduler.process_utterance(CALL_ID, _utterance(0))
    scheduler.process_utterance("call-2", _utterance(0))

    assert len(executor.queued) == 2


def test_a_failing_analysis_does_not_block_later_ones():
    cluster = _cluster(InMemoryLiveStateStore())
    executor = QueueExecutor()
    calls = []

    class Failing(CountingWorkflow):
        def analyze_latest_speech(self, call_id):
            calls.append(call_id)
            if len(calls) == 1:
                raise RuntimeError("LLM rate limited")
            return super().analyze_latest_speech(call_id)

    scheduler = LiveAnalysisScheduler(Failing(cluster.a), executor=executor)
    scheduler.process_utterance(CALL_ID, _utterance(0))
    executor.run_all()
    scheduler.process_utterance(CALL_ID, _utterance(1))
    executor.run_all()

    assert len(calls) == 2
    assert cluster.a.analyze_call(CALL_ID).sentiment == _SENTIMENT


def test_analysis_finishing_after_completion_is_discarded():
    cluster = _cluster(InMemoryLiveStateStore())
    cluster.a.record_utterance(CALL_ID, _utterance(0))
    cluster.a.complete_call(CALL_ID, 99.0)
    final = cluster.a.analyze_call(CALL_ID)

    assert cluster.a.analyze_latest_speech(CALL_ID) is None
    assert cluster.a.analyze_call(CALL_ID).coverage.complaints == final.coverage.complaints


def test_background_analysis_runs_on_real_threads():
    cluster = _cluster(InMemoryLiveStateStore())
    scheduler = LiveAnalysisScheduler(cluster.a)

    scheduler.process_utterance(CALL_ID, _utterance(0))

    assert scheduler.wait_until_idle(timeout=10)
    assert cluster.a.analyze_call(CALL_ID).sentiment == _SENTIMENT
