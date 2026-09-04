import asyncio
from datetime import datetime, timezone

import pytest

from bap.core.engine.scheduler import JobRun, ScheduledJob, Scheduler
from bap.core.engine.tab_session import TickReport, TickStatus


def make_report(profile_id: str, tick_number: int) -> TickReport:
    now = datetime.now(timezone.utc)
    return TickReport(
        profile_id=profile_id,
        tick_number=tick_number,
        status=TickStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )


class FakeSession:
    def __init__(self, profile_id: str):
        self._profile_id = profile_id
        self.ticks = 0

    @property
    def profile_id(self) -> str:
        return self._profile_id

    async def tick(self) -> TickReport:
        self.ticks += 1
        return make_report(self._profile_id, self.ticks)


class RaisingSession(FakeSession):
    async def tick(self) -> TickReport:
        self.ticks += 1
        raise RuntimeError("session contract violated")


class BlockingSession(FakeSession):
    """Tick blocks until released, so shutdown-while-in-flight is testable."""

    def __init__(self, profile_id: str):
        super().__init__(profile_id)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = 0

    async def tick(self) -> TickReport:
        self.ticks += 1
        self.entered.set()
        await self.release.wait()
        self.completed += 1
        return make_report(self._profile_id, self.ticks)


class RecordingSleep:
    """Instant sleep that records every requested delay (in seconds)."""

    def __init__(self):
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)


async def wait_until(predicate, *, tries: int = 500):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


def job(session, interval_ms=1000, jitter_ms=0) -> ScheduledJob:
    return ScheduledJob(session=session, interval_ms=interval_ms, jitter_ms=jitter_ms)


# --- run_once -------------------------------------------------------------------


async def test_run_once_ticks_single_session_and_returns_report():
    session = FakeSession("p1")
    scheduler = Scheduler()
    scheduler.add_job(job(session))

    runs = await scheduler.run_once()

    assert session.ticks == 1
    assert len(runs) == 1
    assert runs[0].profile_id == "p1"
    assert runs[0].report.tick_number == 1
    assert runs[0].error is None
    assert scheduler.runs_of("p1") == 1


async def test_run_once_ticks_all_sessions_in_registration_order():
    a, b, c = FakeSession("a"), FakeSession("b"), FakeSession("c")
    scheduler = Scheduler()
    for s in (a, b, c):
        scheduler.add_job(job(s))

    runs = await scheduler.run_once()

    assert [r.profile_id for r in runs] == ["a", "b", "c"]
    assert (a.ticks, b.ticks, c.ticks) == (1, 1, 1)


async def test_run_once_contains_a_raising_session_and_continues():
    bad, good = RaisingSession("bad"), FakeSession("good")
    scheduler = Scheduler()
    scheduler.add_job(job(bad))
    scheduler.add_job(job(good))

    runs = await scheduler.run_once()

    assert isinstance(runs[0].error, RuntimeError)
    assert runs[0].report is None
    assert runs[1].report is not None
    assert good.ticks == 1


# --- registration ------------------------------------------------------------------


def test_duplicate_profile_rejected():
    scheduler = Scheduler()
    scheduler.add_job(job(FakeSession("p1")))

    with pytest.raises(ValueError, match="already registered"):
        scheduler.add_job(job(FakeSession("p1")))


def test_remove_job_deregisters_profile():
    scheduler = Scheduler()
    scheduler.add_job(job(FakeSession("p1")))
    scheduler.add_job(job(FakeSession("p2")))

    scheduler.remove_job("p1")

    assert scheduler.profile_ids == ("p2",)


def test_remove_unknown_job_raises():
    with pytest.raises(ValueError, match="No job registered"):
        Scheduler().remove_job("ghost")


async def test_remove_job_while_running_is_rejected():
    scheduler = Scheduler(sleep=RecordingSleep())
    scheduler.add_job(job(FakeSession("p1")))
    await scheduler.start()
    try:
        with pytest.raises(RuntimeError, match="while the scheduler is running"):
            scheduler.remove_job("p1")
    finally:
        await scheduler.stop()


@pytest.mark.parametrize("interval_ms,jitter_ms", [(0, 0), (-5, 0), (100, -1)])
def test_job_timing_configuration_is_validated(interval_ms, jitter_ms):
    with pytest.raises(ValueError):
        ScheduledJob(session=FakeSession("p1"), interval_ms=interval_ms, jitter_ms=jitter_ms)


async def test_add_job_while_running_is_rejected():
    scheduler = Scheduler(sleep=RecordingSleep())
    scheduler.add_job(job(FakeSession("p1")))
    await scheduler.start()
    try:
        with pytest.raises(RuntimeError, match="while the scheduler is running"):
            scheduler.add_job(job(FakeSession("p2")))
    finally:
        await scheduler.stop()


# --- interval and jitter ---------------------------------------------------------------


async def test_loop_sleeps_the_configured_interval_between_ticks():
    session = FakeSession("p1")
    sleep = RecordingSleep()
    scheduler = Scheduler(sleep=sleep)
    scheduler.add_job(job(session, interval_ms=750))

    await scheduler.start()
    await wait_until(lambda: session.ticks >= 3)
    await scheduler.stop()

    assert sleep.delays[:2] == [0.75, 0.75]


async def test_jitter_is_added_deterministically_from_injected_rng():
    session = FakeSession("p1")
    sleep = RecordingSleep()
    scheduler = Scheduler(sleep=sleep, rng=lambda: 0.5)
    scheduler.add_job(job(session, interval_ms=1000, jitter_ms=400))

    await scheduler.start()
    await wait_until(lambda: session.ticks >= 2)
    await scheduler.stop()

    assert sleep.delays[0] == pytest.approx(1.2)  # 1000ms + 0.5 * 400ms


async def test_zero_jitter_never_consults_rng():
    def exploding_rng() -> float:
        raise AssertionError("rng must not be called when jitter is 0")

    session = FakeSession("p1")
    scheduler = Scheduler(sleep=RecordingSleep(), rng=exploding_rng)
    scheduler.add_job(job(session, interval_ms=100, jitter_ms=0))

    await scheduler.start()
    await wait_until(lambda: session.ticks >= 2)
    await scheduler.stop()


# --- lifecycle -----------------------------------------------------------------------


async def test_start_drives_repeated_ticks_and_stop_halts_them():
    session = FakeSession("p1")
    scheduler = Scheduler(sleep=RecordingSleep())
    scheduler.add_job(job(session))

    await scheduler.start()
    assert scheduler.running
    await wait_until(lambda: session.ticks >= 3)
    await scheduler.stop()
    assert not scheduler.running

    ticks_after_stop = session.ticks
    for _ in range(20):
        await asyncio.sleep(0)
    assert session.ticks == ticks_after_stop


async def test_start_is_idempotent_and_scheduler_is_restartable():
    session = FakeSession("p1")
    scheduler = Scheduler(sleep=RecordingSleep())
    scheduler.add_job(job(session))

    await scheduler.start()
    await scheduler.start()  # no-op, must not spawn duplicate loops
    await wait_until(lambda: session.ticks >= 1)
    first_round = session.ticks
    await scheduler.stop()
    await scheduler.stop()  # idempotent

    await scheduler.start()
    await wait_until(lambda: session.ticks >= first_round + 1)
    await scheduler.stop()


async def test_stop_waits_for_in_flight_tick_to_complete():
    session = BlockingSession("p1")
    scheduler = Scheduler(sleep=RecordingSleep())
    scheduler.add_job(job(session))

    await scheduler.start()
    await session.entered.wait()

    stopping = asyncio.create_task(scheduler.stop())
    for _ in range(10):
        await asyncio.sleep(0)
    assert not stopping.done()  # graceful: waiting for the tick, not killing it

    session.release.set()
    await asyncio.wait_for(stopping, timeout=2.0)

    assert session.completed == 1
    assert not scheduler.running


# --- failure isolation ------------------------------------------------------------------


async def test_one_failing_session_does_not_stop_the_others():
    bad, good = RaisingSession("bad"), FakeSession("good")
    scheduler = Scheduler(sleep=RecordingSleep())
    scheduler.add_job(job(bad, interval_ms=100))
    scheduler.add_job(job(good, interval_ms=100))

    await scheduler.start()
    await wait_until(lambda: good.ticks >= 3 and bad.ticks >= 3)
    await scheduler.stop()

    assert scheduler.runs_of("bad") >= 3  # its own loop also survived


async def test_broken_report_callback_does_not_stall_the_loop():
    def broken_callback(report):
        raise RuntimeError("observer bug")

    session = FakeSession("p1")
    scheduler = Scheduler(sleep=RecordingSleep(), on_report=broken_callback)
    scheduler.add_job(job(session))

    await scheduler.start()
    await wait_until(lambda: session.ticks >= 3)
    await scheduler.stop()


# --- reporting ---------------------------------------------------------------------------


async def test_on_report_callback_receives_every_report():
    seen: list[TickReport] = []

    async def collect(report):  # async callback supported
        seen.append(report)

    scheduler = Scheduler(on_report=collect)
    scheduler.add_job(job(FakeSession("p1")))
    scheduler.add_job(job(FakeSession("p2")))

    await scheduler.run_once()

    assert [r.profile_id for r in seen] == ["p1", "p2"]


async def test_run_once_rejected_while_running():
    scheduler = Scheduler(sleep=RecordingSleep())
    scheduler.add_job(job(FakeSession("p1")))
    await scheduler.start()
    try:
        with pytest.raises(RuntimeError, match="not available while"):
            await scheduler.run_once()
    finally:
        await scheduler.stop()


# --- state isolation --------------------------------------------------------------------


async def test_no_state_leaks_between_scheduler_instances():
    session = FakeSession("p1")

    first = Scheduler()
    first.add_job(job(session))
    await first.run_once()

    second = Scheduler()
    second.add_job(job(session))

    assert second.runs_of("p1") == 0  # fresh scheduler, fresh counters
    assert first.runs_of("p1") == 1
    assert second.profile_ids == ("p1",)
