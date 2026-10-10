"""Background jobs over a long day: an LLM that is rate limited for hours,
a repair sweep that outlasts its lock, deliveries that can never be retried
piling up, and a job that stops running."""

import threading

import httpx

from app.domain.customer_summary_delivery import DeliveryStatus
from app.services.background_jobs import BackgroundJobRunner, PeriodicJob
from app.services.customer_summary_delivery_service import (
    RETRY_WINDOW_SECONDS,
    CustomerSummaryDeliveryService,
)
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.services.customer_summary_repository import InMemoryCustomerSummaryDeliveryRepository
from app.services.live_state_store import InMemoryLiveStateStore, RedisLiveStateStore
from app.services.post_call_repair_service import (
    RATE_LIMIT_GAVE_UP_ERROR,
    RATE_LIMITED_ERROR,
    PostCallRepairService,
)
from app.services.post_call_summary_repository import InMemoryPostCallSummaryRepository
from tests.test_production_readiness import Clock, Processor, _completed_calls
from tests.test_sms_gate_provider import Gateway, accepted, contact, provider, summary

HOUR = 3600.0


# ---- The text-retry batch ----

def test_deliveries_that_can_never_be_retried_do_not_block_newer_ones():
    repository = InMemoryCustomerSummaryDeliveryRepository()
    gateway = Gateway(httpx.Response(503), accepted("gw-new"))
    service = CustomerSummaryDeliveryService(
        provider=provider(gateway),
        message_service=CustomerSummaryMessageService(),
        repository=repository,
        max_attempts=5,
    )
    failed = service.deliver_for_call(summary(), lambda call_id: contact())
    assert failed.status is DeliveryStatus.FAILED

    # Sixty older deliveries that are finished for good: thirty used up
    # their attempts, thirty are past the day in which a text is retried.
    for index in range(60):
        used_up = index < 30
        repository.save(
            failed.__class__(
                delivery_id=f"dead-{index}",
                customer_id="C-old",
                call_id=f"old-{index}",
                channel=failed.channel,
                status=DeliveryStatus.FAILED,
                message="Old summary",
                idempotency_key=f"customer-summary:old-{index}:C-old:sms",
                attempts=5 if used_up else 1,
                created_at=failed.created_at - (1 if used_up else RETRY_WINDOW_SECONDS + 1),
                updated_at=failed.updated_at - 1000 + index,  # all longer untouched
            )
        )

    sent = service.retry_unfinished(
        lambda call_id: summary() if call_id == "call-1" else None, lambda call_id: contact()
    )

    assert sent == 1
    assert repository.get_by_idempotency_key(failed.idempotency_key).status is DeliveryStatus.SENT


def test_list_unfinished_leaves_out_what_cannot_be_retried():
    repository = InMemoryCustomerSummaryDeliveryRepository()
    gateway = Gateway(httpx.Response(503))
    service = CustomerSummaryDeliveryService(provider=provider(gateway), repository=repository)
    failed = service.send_summary_to_customer(summary(), contact())

    assert repository.list_unfinished(10) == (failed,)
    assert repository.list_unfinished(10, max_attempts=1) == ()
    assert repository.list_unfinished(10, max_attempts=2) == (failed,)
    assert repository.list_unfinished(10, created_after=failed.created_at) == ()
    assert repository.list_unfinished(10, created_after=failed.created_at - 1) == (failed,)


# ---- A rate limit that lasts for hours ----

class _RateLimits:
    """What the post-call processor reports after each attempt."""

    def __init__(self) -> None:
        self.wait: float | None = None

    def __call__(self, call_id: str) -> float | None:
        return self.wait


def _repair(calls, results, clock, limits, store=None):
    summaries = InMemoryPostCallSummaryRepository()
    process = Processor(summaries, results)
    service = PostCallRepairService(
        calls,
        process,
        summaries,
        store or InMemoryLiveStateStore(clock),
        min_age_seconds=100,
        max_attempts=3,
        clock=clock,
        rate_limit_wait=limits,
        rate_limit_retry_seconds=HOUR,
        rate_limit_give_up_seconds=24 * HOUR,
    )
    return service, process


def test_a_rate_limited_call_is_not_given_up_on_and_is_retried_hourly():
    clock, limits = Clock(), _RateLimits()
    calls = _completed_calls("c1")
    # Refused twenty times (well past max_attempts), then it works.
    service, process = _repair(calls, [None] * 20 + ["ok"], clock, limits)
    limits.wait = 7 * HOUR  # a daily limit

    service.run()  # first noticed
    clock.now += 100
    run = service.run()
    assert run.failed == 1 and run.skipped_reason is not None
    (pending,) = service.pending()
    assert pending.attempts == 0 and not pending.gave_up
    assert pending.last_error == RATE_LIMITED_ERROR

    # Sweeps keep coming every five minutes; the call is tried once an hour.
    for _ in range(11):
        clock.now += 300
        service.run()
    assert len(process.calls) == 1
    clock.now += 300
    service.run()
    assert len(process.calls) == 2

    for _ in range(18):
        clock.now += HOUR
        service.run()
    assert len(process.calls) == 20
    assert not service.pending()[0].gave_up

    limits.wait = None  # the limit has cleared
    clock.now += HOUR
    assert service.run().repaired == 1
    assert len(process.calls) == 21


def test_a_short_limit_is_retried_as_soon_as_it_clears():
    clock, limits = Clock(), _RateLimits()
    service, process = _repair(_completed_calls("c1"), [None, "ok"], clock, limits)
    limits.wait = 90.0

    service.run()
    clock.now += 100
    service.run()
    limits.wait = None
    clock.now += 100  # past the 90 s the LLM asked for

    assert service.run().repaired == 1


def test_one_refusal_stops_the_sweep_for_the_other_calls():
    clock, limits = Clock(), _RateLimits()
    service, process = _repair(_completed_calls("c1", "c2", "c3"), [None] * 9, clock, limits)
    limits.wait = 7 * HOUR

    service.run()
    clock.now += 100
    run = service.run()

    # The first refusal is enough: the others would be refused too.
    assert len(process.calls) == 1
    assert run.pending == 3 and run.failed == 1


def test_a_call_still_rate_limited_after_a_day_is_given_up_on():
    clock, limits = Clock(), _RateLimits()
    service, process = _repair(_completed_calls("c1"), [None] * 40, clock, limits)
    limits.wait = 7 * HOUR

    service.run()
    for _ in range(26):
        clock.now += HOUR
        service.run()

    (pending,) = service.pending()
    assert pending.gave_up
    assert pending.last_error == RATE_LIMIT_GAVE_UP_ERROR
    tried = len(process.calls)
    clock.now += HOUR
    assert service.run().gave_up == 1 and len(process.calls) == tried


def test_other_failures_still_use_up_attempts():
    clock, limits = Clock(), _RateLimits()
    service, process = _repair(_completed_calls("c1"), [None] * 9, clock, limits)

    service.run()
    for _ in range(10):
        clock.now += 1000
        service.run()

    assert service.pending()[0].gave_up
    assert len(process.calls) == 3


def test_the_processor_reports_a_rate_limit_and_forgets_it_on_the_next_try():
    # The real workflow, with an LLM that refuses once.
    from tests.test_post_call_rate_limits import CALL_ID, FlakyComplaints, _completed_call

    workflow, _ = _completed_call(FlakyComplaints(failures=1, retry_after=25_000.0))
    assert workflow.post_call_rate_limit_wait(CALL_ID) is None

    assert workflow.process_completed_call(CALL_ID) is None
    assert workflow.post_call_rate_limit_wait(CALL_ID) == 25_000.0

    assert workflow.process_completed_call(CALL_ID) is not None
    assert workflow.post_call_rate_limit_wait(CALL_ID) is None


# ---- A sweep that outlasts its lock ----

def test_a_lock_is_renewed_only_by_its_holder():
    clock = Clock()
    store = InMemoryLiveStateStore(clock)
    token = store.acquire_lock("job", 100)

    clock.now += 90
    assert store.renew_lock("job", token, 100) is True
    clock.now += 90  # past the first expiry, inside the renewed one
    assert store.acquire_lock("job", 100) is None
    assert store.renew_lock("job", "someone-else", 100) is False

    clock.now += 200  # expired: another instance takes it
    other = store.acquire_lock("job", 100)
    assert other is not None
    assert store.renew_lock("job", token, 100) is False


class _Redis:
    """Enough of redis-py for the lock scripts (no expiry)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expires: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, key):
        self.data.pop(key, None)

    def eval(self, script, numkeys, key, token, *args):
        if self.data.get(key) != token:
            return 0
        if "expire" in script:
            self.expires[key] = args[0]
        else:
            del self.data[key]
        return 1

    def ping(self):
        return True


def test_the_redis_lock_is_renewed_only_by_its_holder():
    redis = _Redis()
    store = RedisLiveStateStore(redis, "test")
    token = store.acquire_lock("job", 100)

    assert store.renew_lock("job", token, 900) is True
    assert list(redis.expires.values()) == ["900"]
    assert store.renew_lock("job", "someone-else", 900) is False
    store.release_lock("job", token)
    assert store.renew_lock("job", token, 900) is False


class _LosesLock(InMemoryLiveStateStore):
    """The lock expires and another instance takes it after the first renewal."""

    renewals = 0

    def renew_lock(self, name, token, ttl_seconds):
        self.renewals += 1
        return self.renewals == 1


def test_a_sweep_that_lost_its_lock_stops():
    clock, limits = Clock(), _RateLimits()
    store = _LosesLock(clock)
    service, process = _repair(
        _completed_calls("c1", "c2", "c3"), ["ok"] * 3, clock, limits, store=store
    )

    service.run()
    clock.now += 100
    run = service.run()

    assert run.repaired == 1 and len(process.calls) == 1


# ---- Seeing that jobs run ----

def test_a_job_that_hangs_shows_as_overdue():
    clock = Clock()
    runner = BackgroundJobRunner([PeriodicJob("sweep", 100.0, lambda: None)], clock=clock)
    assert runner.overdue_by() == {}  # not started: nothing to report

    runner._last_run_at["sweep"] = clock.now  # as start() records it
    clock.now += 100
    assert runner.overdue_by() == {"sweep": 1.0}
    clock.now += 400  # no run has ended since
    assert runner.overdue_by() == {"sweep": 5.0}


def test_each_finished_run_is_recorded_even_when_it_fails():
    runs = threading.Semaphore(0)

    def failing():
        runs.release()
        raise RuntimeError("boom")

    clock = Clock()
    runner = BackgroundJobRunner([PeriodicJob("flaky", 0.02, failing)], clock=clock)
    runner.start()
    started_at = runner._last_run_at["flaky"]
    clock.now += 50
    assert runs.acquire(timeout=2) and runs.acquire(timeout=2)
    runner.stop()

    assert runner._last_run_at["flaky"] == started_at + 50
