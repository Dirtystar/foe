import asyncio
from datetime import datetime, timezone

import pytest

from bap.core.domain.models import TabHandle, TabProfile
from bap.core.engine.scheduler import Scheduler
from bap.core.engine.session_manager import (
    DuplicateSessionError,
    SessionLimitError,
    SessionManager,
    SessionNotFoundError,
    SessionSpec,
)
from bap.core.engine.tab_session import TickReport, TickStatus
from bap.core.ports.browser_port import BrowserManagerError, BrowserPort


class FakeBrowser(BrowserPort):
    def __init__(self, *, fail_open_for: set[str] = frozenset()):
        self.fail_open_for = set(fail_open_for)
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0
        self.open_profiles: list[TabProfile] = []
        self.open_tab_ids: list[str] = []
        self.closed_tab_ids: list[str] = []

    async def start(self):
        self.started = True
        self.start_calls += 1

    async def stop(self):
        self.started = False
        self.stop_calls += 1

    async def open_tab(self, profile: TabProfile) -> TabHandle:
        if profile.id in self.fail_open_for:
            raise BrowserManagerError(f"cannot open '{profile.id}'")
        self.open_profiles.append(profile)
        self.open_tab_ids.append(profile.id)
        return TabHandle(tab_id=profile.id, native=object())

    async def navigate(self, tab, url):
        pass

    async def close_tab(self, tab: TabHandle):
        self.closed_tab_ids.append(tab.tab_id)

    def list_tabs(self):
        return [t for t in self.open_tab_ids if t not in self.closed_tab_ids]


class FakeSession:
    def __init__(self, profile_id: str):
        self._profile_id = profile_id
        self.ticks = 0

    @property
    def profile_id(self) -> str:
        return self._profile_id

    async def tick(self) -> TickReport:
        self.ticks += 1
        now = datetime.now(timezone.utc)
        return TickReport(
            profile_id=self._profile_id,
            tick_number=self.ticks,
            status=TickStatus.COMPLETED,
            started_at=now,
            finished_at=now,
        )


class RecordingFactory:
    """Builds FakeSessions; records what it was asked to build; can fail."""

    def __init__(self, *, fail_for: set[str] = frozenset()):
        self.fail_for = set(fail_for)
        self.calls: list[tuple[SessionSpec, TabHandle]] = []
        self.built: dict[str, FakeSession] = {}

    def __call__(self, spec: SessionSpec, tab: TabHandle) -> FakeSession:
        self.calls.append((spec, tab))
        if spec.profile_id in self.fail_for:
            raise RuntimeError(f"factory cannot build '{spec.profile_id}'")
        session = FakeSession(spec.profile_id)
        self.built[spec.profile_id] = session
        return session


def spec(profile_id: str, interval_ms: int = 1000) -> SessionSpec:
    return SessionSpec(
        tab_profile=TabProfile(id=profile_id, start_url=f"https://example.com/{profile_id}"),
        interval_ms=interval_ms,
    )


def make_manager(*, browser=None, scheduler=None, factory=None, max_sessions=8):
    browser = browser if browser is not None else FakeBrowser()
    scheduler = scheduler if scheduler is not None else Scheduler()
    factory = factory if factory is not None else RecordingFactory()
    manager = SessionManager(
        browser=browser, scheduler=scheduler, session_factory=factory, max_sessions=max_sessions
    )
    return manager, browser, scheduler, factory


# --- creation --------------------------------------------------------------------


async def test_create_session_opens_tab_builds_session_and_registers_job():
    manager, browser, scheduler, factory = make_manager()

    profile_id = await manager.create_session(spec("p1"))

    assert profile_id == "p1"
    assert browser.open_tab_ids == ["p1"]
    assert factory.calls[0][0].profile_id == "p1"
    assert scheduler.profile_ids == ("p1",)
    assert manager.profile_ids == ("p1",)


async def test_manager_never_starts_or_stops_the_browser():
    # Browser open/close is BrowserController's job now; the manager only opens
    # and closes tabs. It must never call browser.start()/stop().
    manager, browser, _, _ = make_manager()

    await manager.create_session(spec("p1"))
    await manager.create_session(spec("p2"))
    await manager.stop_automation()

    assert browser.start_calls == 0
    assert browser.stop_calls == 0


async def test_duplicate_session_rejected_without_touching_the_browser():
    manager, browser, _, _ = make_manager()
    await manager.create_session(spec("p1"))

    with pytest.raises(DuplicateSessionError):
        await manager.create_session(spec("p1"))

    assert browser.open_tab_ids == ["p1"]  # no second tab was attempted


async def test_max_sessions_enforced_before_any_resource_is_acquired():
    manager, browser, _, _ = make_manager(max_sessions=2)
    await manager.create_session(spec("p1"))
    await manager.create_session(spec("p2"))

    with pytest.raises(SessionLimitError):
        await manager.create_session(spec("p3"))

    assert browser.open_tab_ids == ["p1", "p2"]
    assert manager.session_count == 2


async def test_multiple_sessions_keep_deterministic_creation_order():
    manager, _, scheduler, _ = make_manager()
    for pid in ("c", "a", "b"):
        await manager.create_session(spec(pid))

    assert manager.profile_ids == ("c", "a", "b")
    assert scheduler.profile_ids == ("c", "a", "b")


# --- failure handling -----------------------------------------------------------------


async def test_browser_open_failure_leaves_no_partial_state():
    browser = FakeBrowser(fail_open_for={"p1"})
    manager, _, scheduler, factory = make_manager(browser=browser)

    with pytest.raises(BrowserManagerError):
        await manager.create_session(spec("p1"))

    assert manager.profile_ids == ()
    assert scheduler.profile_ids == ()
    assert factory.calls == []
    # a later attempt with a working browser proceeds normally
    browser.fail_open_for.clear()
    await manager.create_session(spec("p1"))
    assert manager.profile_ids == ("p1",)


async def test_factory_failure_closes_the_already_opened_tab():
    factory = RecordingFactory(fail_for={"p1"})
    manager, browser, scheduler, _ = make_manager(factory=factory)

    with pytest.raises(RuntimeError, match="factory cannot build"):
        await manager.create_session(spec("p1"))

    assert browser.closed_tab_ids == ["p1"]  # acquired tab was released
    assert manager.profile_ids == ()
    assert scheduler.profile_ids == ()


async def test_one_session_failing_to_close_does_not_destroy_the_others():
    manager, browser, scheduler, factory = make_manager()
    await manager.create_session(spec("p1"))
    await manager.create_session(spec("p2"))

    original_close = browser.close_tab

    async def close_tab(tab):
        if tab.tab_id == "p1":
            raise BrowserManagerError("tab crashed")
        await original_close(tab)

    browser.close_tab = close_tab

    errors = await manager.stop_automation()

    assert [pid for pid, _ in errors] == ["p1"]
    assert "p2" in browser.closed_tab_ids  # p2 still got closed
    assert manager.profile_ids == ()
    assert browser.stop_calls == 0  # the manager never stops the browser


# --- close_session ---------------------------------------------------------------------


async def test_close_session_removes_job_and_closes_tab():
    manager, browser, scheduler, _ = make_manager()
    await manager.create_session(spec("p1"))
    await manager.create_session(spec("p2"))

    await manager.close_session("p1")

    assert manager.profile_ids == ("p2",)
    assert scheduler.profile_ids == ("p2",)
    assert browser.closed_tab_ids == ["p1"]


async def test_close_unknown_session_raises():
    manager, _, _, _ = make_manager()

    with pytest.raises(SessionNotFoundError):
        await manager.close_session("ghost")


async def test_close_session_while_scheduler_runs_keeps_other_sessions_ticking():
    scheduler = Scheduler(sleep=_instant_sleep)
    manager, _, _, factory = make_manager(scheduler=scheduler)
    await manager.create_session(spec("p1", interval_ms=10))
    await manager.create_session(spec("p2", interval_ms=10))

    await scheduler.start()
    try:
        await manager.close_session("p1")
        assert scheduler.running  # resumed automatically after the removal
        p2 = factory.built["p2"]
        before = p2.ticks
        await _wait_until(lambda: p2.ticks > before)
    finally:
        await scheduler.stop()

    assert scheduler.profile_ids == ("p2",)


# --- shutdown and restart ------------------------------------------------------------------


async def test_stop_automation_detaches_everything_but_leaves_browser_open():
    scheduler = Scheduler(sleep=_instant_sleep)
    manager, browser, _, _ = make_manager(scheduler=scheduler)
    await manager.create_session(spec("p1"))
    await manager.create_session(spec("p2"))
    await scheduler.start()

    errors = await manager.stop_automation()

    assert errors == ()
    assert not scheduler.running
    assert scheduler.profile_ids == ()
    assert sorted(browser.closed_tab_ids) == ["p1", "p2"]
    assert browser.stop_calls == 0  # browser lifecycle is not the manager's job
    assert manager.profile_ids == ()


async def test_stop_automation_when_nothing_was_created_is_a_no_op():
    manager, browser, _, _ = make_manager()

    errors = await manager.stop_automation()

    assert errors == ()
    assert browser.stop_calls == 0
    assert browser.closed_tab_ids == []


async def test_manager_is_restartable_after_stop_automation():
    manager, browser, scheduler, _ = make_manager()
    await manager.create_session(spec("p1"))
    await manager.stop_automation()

    await manager.create_session(spec("p1"))  # same id is free again

    assert manager.profile_ids == ("p1",)
    assert scheduler.profile_ids == ("p1",)


# --- wiring -------------------------------------------------------------------------------


async def test_factory_receives_the_spec_and_the_tab_the_browser_opened():
    manager, browser, _, factory = make_manager()
    s = spec("p1")

    await manager.create_session(s)

    given_spec, given_tab = factory.calls[0]
    assert given_spec is s
    assert given_tab.tab_id == "p1"
    assert browser.open_profiles[0] is s.tab_profile


async def test_scheduler_receives_the_factory_built_sessions():
    scheduler = Scheduler()
    manager, _, _, factory = make_manager(scheduler=scheduler)
    await manager.create_session(spec("p1"))
    await manager.create_session(spec("p2"))

    runs = await scheduler.run_once()

    assert [r.profile_id for r in runs] == ["p1", "p2"]
    assert factory.built["p1"].ticks == 1
    assert factory.built["p2"].ticks == 1


async def test_create_session_while_scheduler_runs_registers_and_resumes():
    scheduler = Scheduler(sleep=_instant_sleep)
    manager, _, _, factory = make_manager(scheduler=scheduler)
    await manager.create_session(spec("p1", interval_ms=10))
    await scheduler.start()
    try:
        await manager.create_session(spec("p2", interval_ms=10))
        assert scheduler.running
        await _wait_until(lambda: factory.built["p2"].ticks >= 1)
    finally:
        await scheduler.stop()


async def test_recover_session_recreates_tab_and_rebuilds_session():
    manager, browser, scheduler, factory = make_manager()
    await manager.create_session(spec("p1"))
    original_session = factory.built["p1"]
    original_factory_calls = len(factory.calls)

    await manager.recover_session("p1")

    # old tab closed, a fresh tab opened for the same profile
    assert browser.closed_tab_ids == ["p1"]
    assert browser.open_tab_ids == ["p1", "p1"]
    # session rebuilt via the factory from the stored spec (fresh engine ->
    # cooldowns reset by design)
    assert len(factory.calls) == original_factory_calls + 1
    assert factory.built["p1"] is not original_session
    assert manager.profile_ids == ("p1",)
    assert scheduler.profile_ids == ("p1",)


async def test_recover_reuses_the_stored_spec():
    manager, _, _, factory = make_manager()
    s = spec("p1", interval_ms=250)
    await manager.create_session(s)

    await manager.recover_session("p1")

    recover_spec, _tab = factory.calls[-1]
    assert recover_spec is s  # same spec object reused for the rebuild


async def test_recover_unknown_session_raises():
    manager, _, _, _ = make_manager()

    with pytest.raises(SessionNotFoundError):
        await manager.recover_session("ghost")


async def test_recover_does_not_disturb_other_sessions():
    manager, _, scheduler, factory = make_manager()
    await manager.create_session(spec("p1"))
    await manager.create_session(spec("p2"))
    p2_session = factory.built["p2"]

    await manager.recover_session("p1")

    assert manager.profile_ids == ("p1", "p2")
    assert factory.built["p2"] is p2_session  # p2 was not rebuilt
    # p1's job was re-registered (order may change); both remain scheduled
    assert set(scheduler.profile_ids) == {"p1", "p2"}


async def test_recovery_failure_drops_the_session_and_reports():
    browser = FakeBrowser()
    manager, _, scheduler, _ = make_manager(browser=browser)
    await manager.create_session(spec("p1"))
    # the recovery reopen will fail
    browser.fail_open_for.add("p1")

    with pytest.raises(BrowserManagerError):
        await manager.recover_session("p1")

    # dropped so it stops ticking rather than looping on a broken session
    assert manager.profile_ids == ()
    assert scheduler.profile_ids == ()


async def test_recover_while_scheduler_running_keeps_others_ticking():
    scheduler = Scheduler(sleep=_instant_sleep)
    manager, _, _, factory = make_manager(scheduler=scheduler)
    await manager.create_session(spec("p1", interval_ms=10))
    await manager.create_session(spec("p2", interval_ms=10))
    await scheduler.start()
    try:
        await manager.recover_session("p1")
        assert scheduler.running  # resumed after recovery
        p2 = factory.built["p2"]
        before = p2.ticks
        await _wait_until(lambda: p2.ticks > before)
    finally:
        await scheduler.stop()


def test_no_hidden_state_between_manager_instances():
    first, _, _, _ = make_manager()
    second, _, _, _ = make_manager()

    assert first.profile_ids == ()
    assert second.profile_ids == ()
    assert first is not second


def test_spec_and_constructor_validation():
    with pytest.raises(ValueError):
        spec("p1", interval_ms=0)
    with pytest.raises(ValueError):
        SessionSpec(tab_profile=TabProfile(id="p1"), interval_ms=100, jitter_ms=-1)
    with pytest.raises(ValueError):
        SessionManager(
            browser=FakeBrowser(),
            scheduler=Scheduler(),
            session_factory=RecordingFactory(),
            max_sessions=0,
        )


# --- helpers -------------------------------------------------------------------------------


async def _instant_sleep(seconds: float) -> None:
    await asyncio.sleep(0)


async def _wait_until(predicate, *, tries: int = 500):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")
