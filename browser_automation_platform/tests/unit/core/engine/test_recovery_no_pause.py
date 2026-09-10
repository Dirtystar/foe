"""Recovery via replace_job never pauses the scheduler."""

import asyncio

import pytest

from bap.core.engine.scheduler import Scheduler
from bap.core.engine.session_manager import SessionManager, SessionSpec
from bap.core.domain.models import TabHandle, TabProfile
from bap.core.engine.tab_session import TickReport, TickStatus
from bap.core.ports.browser_port import BrowserPort


class FakeBrowser(BrowserPort):
    def __init__(self, *, fail_open_for=frozenset()):
        self.fail_open_for = set(fail_open_for)
        self.started = False
        self.opens = {}
        self.closed = []

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def open_tab(self, profile):
        if profile.id in self.fail_open_for:
            from bap.core.ports.browser_port import BrowserManagerError

            raise BrowserManagerError(f"cannot open {profile.id}")
        self.opens[profile.id] = self.opens.get(profile.id, 0) + 1
        return TabHandle(tab_id=profile.id, native=None)

    async def navigate(self, tab, url):
        pass

    async def close_tab(self, tab):
        self.closed.append(tab.tab_id)

    def list_tabs(self):
        return []


class FakeSession:
    def __init__(self, profile_id):
        self._profile_id = profile_id
        self.ticks = 0

    @property
    def profile_id(self):
        return self._profile_id

    async def tick(self):
        self.ticks += 1
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        return TickReport(
            profile_id=self._profile_id, tick_number=self.ticks,
            status=TickStatus.COMPLETED, started_at=now, finished_at=now,
        )


class RecordingFactory:
    def __init__(self):
        self.built = {}

    def __call__(self, spec, tab):
        s = FakeSession(spec.profile_id)
        self.built[spec.profile_id] = s
        return s


async def _instant(_s):
    await asyncio.sleep(0)


async def _wait_until(predicate, *, tries=20000):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never met")


def spec(pid):
    return SessionSpec(tab_profile=TabProfile(id=pid), interval_ms=10)


def make_manager(browser=None, factory=None):
    browser = browser or FakeBrowser()
    factory = factory or RecordingFactory()
    scheduler = Scheduler(sleep=_instant)
    manager = SessionManager(
        browser=browser, scheduler=scheduler, session_factory=factory, max_sessions=8
    )
    return manager, browser, scheduler, factory


async def test_recovery_while_running_does_not_stop_scheduler():
    manager, browser, scheduler, factory = make_manager()
    await manager.create_session(spec("a"))
    await manager.create_session(spec("b"))
    await scheduler.start()
    try:
        await _wait_until(lambda: factory.built["a"].ticks >= 2 and factory.built["b"].ticks >= 2)

        b_before = factory.built["b"].ticks
        stopped_observed = {"seen": False}

        async def watch():
            for _ in range(500):
                if not scheduler.running:
                    stopped_observed["seen"] = True
                await asyncio.sleep(0)

        watcher = asyncio.create_task(watch())
        await manager.recover_session("a")  # replace_job under the hood
        await watcher

        assert not stopped_observed["seen"]  # scheduler never stopped
        assert scheduler.running
        assert browser.opens["a"] == 2  # tab recreated
        # 'a' recovered to a fresh session that ticks; 'b' kept going
        new_a = factory.built["a"]
        await _wait_until(lambda: new_a.ticks >= 1)
        await _wait_until(lambda: factory.built["b"].ticks >= b_before + 3)
    finally:
        await scheduler.stop()


async def test_multiple_sessions_recover_concurrently_while_running():
    manager, browser, scheduler, factory = make_manager()
    for pid in ("a", "b", "c", "d"):
        await manager.create_session(spec(pid))
    await scheduler.start()
    try:
        await _wait_until(lambda: all(factory.built[p].ticks >= 1 for p in "abcd"))

        await asyncio.gather(*(manager.recover_session(p) for p in "abcd"))

        assert scheduler.running
        assert set(manager.profile_ids) == set("abcd")  # none lost
        assert set(scheduler.profile_ids) == set("abcd")  # none duplicated
        assert all(browser.opens[p] == 2 for p in "abcd")  # each recreated once
    finally:
        await scheduler.stop()


async def test_failed_replacement_leaves_scheduler_consistent():
    browser = FakeBrowser()
    manager, browser, scheduler, factory = make_manager(browser=browser)
    await manager.create_session(spec("a"))
    await manager.create_session(spec("b"))
    await scheduler.start()
    try:
        await _wait_until(lambda: factory.built["b"].ticks >= 2)
        browser.fail_open_for.add("a")  # recovery reopen will fail

        with pytest.raises(Exception):
            await manager.recover_session("a")

        # 'a' dropped and stops ticking; 'b' unaffected; scheduler still running
        assert scheduler.running
        assert "a" not in manager.profile_ids
        assert "a" not in scheduler.profile_ids
        assert "b" in scheduler.profile_ids
        b_now = factory.built["b"].ticks
        await _wait_until(lambda: factory.built["b"].ticks >= b_now + 3)
    finally:
        await scheduler.stop()
