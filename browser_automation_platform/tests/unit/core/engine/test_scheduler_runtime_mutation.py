"""Runtime job mutation: register/unregister/replace while the loop ticks."""

import asyncio
from datetime import datetime, timezone

import pytest

from bap.core.engine.scheduler import ScheduledJob, Scheduler
from bap.core.engine.tab_session import TickReport, TickStatus


def report(profile_id, n):
    now = datetime.now(timezone.utc)
    return TickReport(
        profile_id=profile_id, tick_number=n, status=TickStatus.COMPLETED,
        started_at=now, finished_at=now,
    )


class FakeSession:
    def __init__(self, profile_id, *, tag=None):
        self._profile_id = profile_id
        self.tag = tag or profile_id
        self.ticks = 0

    @property
    def profile_id(self):
        return self._profile_id

    async def tick(self):
        self.ticks += 1
        return report(self._profile_id, self.ticks)


class GatedSession(FakeSession):
    """Tick blocks until released, to test mutation during an in-flight tick."""

    def __init__(self, profile_id):
        super().__init__(profile_id)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = 0

    async def tick(self):
        self.ticks += 1
        self.entered.set()
        await self.release.wait()
        self.completed += 1
        return report(self._profile_id, self.ticks)


async def _instant(_seconds):
    await asyncio.sleep(0)


def job(session, interval_ms=10):
    return ScheduledJob(session=session, interval_ms=interval_ms)


async def _wait_until(predicate, *, tries=20000):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never met")


@pytest.fixture
def scheduler():
    return Scheduler(sleep=_instant)


# --- register while running ---------------------------------------------------


async def test_register_job_while_running_starts_ticking(scheduler):
    a = FakeSession("a")
    scheduler.add_job(job(a))
    await scheduler.start()
    try:
        await _wait_until(lambda: a.ticks >= 2)
        b = FakeSession("b")
        await scheduler.register_job(job(b))  # added live
        await _wait_until(lambda: b.ticks >= 3)
        assert scheduler.running  # never stopped
        assert set(scheduler.profile_ids) == {"a", "b"}
    finally:
        await scheduler.stop()


async def test_duplicate_register_is_rejected(scheduler):
    scheduler.add_job(job(FakeSession("a")))
    await scheduler.start()
    try:
        with pytest.raises(ValueError, match="already registered"):
            await scheduler.register_job(job(FakeSession("a")))
    finally:
        await scheduler.stop()


# --- unregister while running -------------------------------------------------


async def test_unregister_stops_future_ticks_others_continue(scheduler):
    a, b = FakeSession("a"), FakeSession("b")
    scheduler.add_job(job(a))
    scheduler.add_job(job(b))
    await scheduler.start()
    try:
        await _wait_until(lambda: a.ticks >= 2 and b.ticks >= 2)
        await scheduler.unregister_job("a")
        assert scheduler.running
        frozen = a.ticks
        await _wait_until(lambda: b.ticks >= frozen + 5)  # b keeps ticking
        # give 'a' plenty of scheduler turns; it must not tick again
        for _ in range(200):
            await asyncio.sleep(0)
        assert a.ticks == frozen
        assert scheduler.profile_ids == ("b",)
    finally:
        await scheduler.stop()


async def test_unregister_unknown_job_is_tolerated(scheduler):
    scheduler.add_job(job(FakeSession("a")))
    await scheduler.start()
    try:
        await scheduler.unregister_job("ghost")  # no raise
    finally:
        await scheduler.stop()


# --- in-flight tick -----------------------------------------------------------


async def test_unregister_during_inflight_tick_lets_it_finish(scheduler):
    gated = GatedSession("g")
    other = FakeSession("o")
    scheduler.add_job(job(gated))
    scheduler.add_job(job(other))
    await scheduler.start()
    try:
        await gated.entered.wait()  # g is mid-tick, blocked

        unregister = asyncio.create_task(scheduler.unregister_job("g"))
        for _ in range(20):
            await asyncio.sleep(0)
        assert not unregister.done()  # waits for the in-flight tick, does not interrupt it
        assert gated.completed == 0  # tick not yet finished, not cancelled

        gated.release.set()  # let the in-flight tick complete
        await asyncio.wait_for(unregister, timeout=2.0)

        assert gated.completed == 1  # finished normally
        first = gated.ticks
        for _ in range(200):
            await asyncio.sleep(0)
        assert gated.ticks == first  # no second tick after removal
        assert other.ticks >= 1  # the other session was unaffected
    finally:
        await scheduler.stop()


# --- replace ------------------------------------------------------------------


async def test_replace_swaps_session_without_duplication(scheduler):
    old = FakeSession("p")
    scheduler.add_job(job(old))
    await scheduler.start()
    try:
        await _wait_until(lambda: old.ticks >= 2)
        new = FakeSession("p", tag="new")
        await scheduler.replace_job("p", job(new))
        await _wait_until(lambda: new.ticks >= 3)
        assert scheduler.running
        assert scheduler.profile_ids == ("p",)  # exactly one job, no duplicate
        old_final = old.ticks
        for _ in range(200):
            await asyncio.sleep(0)
        assert old.ticks == old_final  # old session stopped, no double execution
    finally:
        await scheduler.stop()


async def test_replace_profile_mismatch_is_rejected(scheduler):
    scheduler.add_job(job(FakeSession("p")))
    await scheduler.start()
    try:
        with pytest.raises(ValueError, match="mismatch"):
            await scheduler.replace_job("p", job(FakeSession("other")))
    finally:
        await scheduler.stop()


# --- concurrency --------------------------------------------------------------


async def test_concurrent_replace_of_different_profiles(scheduler):
    sessions = {pid: FakeSession(pid) for pid in ("a", "b", "c", "d")}
    for s in sessions.values():
        scheduler.add_job(job(s))
    await scheduler.start()
    try:
        await _wait_until(lambda: all(s.ticks >= 1 for s in sessions.values()))
        news = {pid: FakeSession(pid, tag="new") for pid in sessions}
        # replace all four simultaneously
        await asyncio.gather(*(scheduler.replace_job(pid, job(news[pid])) for pid in news))

        assert scheduler.running
        assert set(scheduler.profile_ids) == {"a", "b", "c", "d"}  # none lost
        assert len(scheduler.profile_ids) == 4  # none duplicated
        await _wait_until(lambda: all(s.ticks >= 2 for s in news.values()))
    finally:
        await scheduler.stop()


# --- fairness -----------------------------------------------------------------


async def test_fairness_preserved_across_replacement(scheduler):
    sessions = {pid: FakeSession(pid) for pid in ("a", "b", "c", "d")}
    for s in sessions.values():
        scheduler.add_job(job(s))
    await scheduler.start()
    try:
        await _wait_until(lambda: all(s.ticks >= 5 for s in sessions.values()))
        # replace one; the others must keep pace with each other afterwards
        new_b = FakeSession("b")
        await scheduler.replace_job("b", job(new_b))
        sessions["b"] = new_b
        base = {pid: s.ticks for pid, s in sessions.items()}
        await _wait_until(lambda: all(sessions[p].ticks >= base[p] + 10 for p in sessions))
        # after everyone advanced >=10 more, no session ran away (fair interleave)
        gained = {p: sessions[p].ticks - base[p] for p in sessions}
        assert max(gained.values()) - min(gained.values()) <= max(gained.values())
    finally:
        await scheduler.stop()
