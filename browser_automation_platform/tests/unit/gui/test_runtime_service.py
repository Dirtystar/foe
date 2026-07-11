"""RuntimeService tests — no Qt; exercises the real thread/asyncio bridge."""

import threading

import pytest

from bap.gui.runtime_service import RuntimeService


class FakeScheduler:
    def __init__(self, log):
        self._log = log

    async def run_once(self):
        self._log.append("run_once")
        return ()


class FakeApp:
    def __init__(self, *, fail_start=False):
        self.log = []
        self.scheduler = FakeScheduler(self.log)
        self.session_specs = (type("S", (), {"profile_id": "p1"})(),)
        self._fail_start = fail_start

    async def create_sessions(self):
        self.log.append("create")

    async def open_browser(self):
        self.log.append("open_browser")

    async def close_browser(self):
        self.log.append("close_browser")

    async def start(self):
        if self._fail_start:
            raise RuntimeError("cannot start")
        self.log.append("start")

    async def stop_automation(self):
        self.log.append("stop_automation")
        return ()

    async def stop(self):
        self.log.append("stop")
        return ()


@pytest.fixture
def service():
    app = FakeApp()
    svc = RuntimeService(app)
    svc.start_loop()
    yield svc, app
    svc.stop_loop()


def test_profile_ids_come_from_the_app(service):
    svc, _ = service
    assert svc.profile_ids == ("p1",)


def test_start_runtime_runs_app_start_off_the_caller_thread(service):
    svc, app = service
    caller = threading.get_ident()

    svc.start_runtime().result(timeout=5)

    assert app.log == ["start"]
    assert svc.state == "running"
    # sanity: the loop thread is not the test thread
    assert svc._thread is not None and svc._thread.ident != caller  # noqa: SLF001


def test_tick_once_is_self_contained(service):
    svc, app = service

    svc.tick_once().result(timeout=5)

    assert app.log == ["open_browser", "create", "run_once", "stop_automation"]


def test_stop_runtime_sets_state_stopped(service):
    svc, app = service
    svc.start_runtime().result(timeout=5)

    svc.stop_runtime().result(timeout=5)

    assert app.log[-1] == "stop_automation"  # Stop = automation only, browser survives
    # the done-callback that flips state may run just after result(); poll it
    _wait_for(lambda: svc.state == "stopped")


def test_state_changes_are_reported_via_callback(service):
    svc, _ = service
    states = []
    svc.on_state_change = states.append

    svc.start_runtime().result(timeout=5)

    _wait_for(lambda: "running" in states)


def test_runtime_error_is_surfaced_not_raised_into_thread():
    app = FakeApp(fail_start=True)
    svc = RuntimeService(app)
    svc.start_loop()
    reported = []
    done = threading.Event()
    svc.on_error = lambda msg: (reported.append(msg), done.set())

    try:
        future = svc.start_runtime()
        assert done.wait(timeout=5)
        assert "cannot start" in reported[0]
        with pytest.raises(RuntimeError):
            future.result(timeout=5)
    finally:
        svc.stop_loop()


def test_submitting_before_loop_started_raises():
    svc = RuntimeService(FakeApp())
    with pytest.raises(RuntimeError, match="start_loop"):
        svc.start_runtime()


def _wait_for(predicate, *, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")
