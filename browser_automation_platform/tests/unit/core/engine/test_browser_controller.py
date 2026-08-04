import pytest

from bap.core.domain.enums import BrowserOwnership
from bap.core.engine.browser_controller import BrowserController
from bap.core.ports.browser_port import BrowserPort


class FakeBrowser(BrowserPort):
    def __init__(self, *, fail_stop: bool = False, ownership=BrowserOwnership.MANAGED):
        self.fail_stop = fail_stop
        self.ownership = ownership
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self):
        self.start_calls += 1

    async def stop(self):
        self.stop_calls += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")

    async def open_tab(self, profile):
        raise NotImplementedError

    async def navigate(self, tab, url):
        raise NotImplementedError

    async def close_tab(self, tab):
        raise NotImplementedError

    def list_tabs(self):
        return []


async def test_open_starts_the_browser_and_marks_open():
    browser = FakeBrowser()
    controller = BrowserController(browser)

    assert not controller.is_open
    await controller.open()

    assert controller.is_open
    assert browser.start_calls == 1


async def test_open_is_idempotent():
    browser = FakeBrowser()
    controller = BrowserController(browser)

    await controller.open()
    await controller.open()

    assert browser.start_calls == 1  # not restarted


async def test_close_stops_the_browser_and_marks_closed():
    browser = FakeBrowser()
    controller = BrowserController(browser)
    await controller.open()

    await controller.close()

    assert not controller.is_open
    assert browser.stop_calls == 1


async def test_close_without_open_is_a_no_op():
    browser = FakeBrowser()
    controller = BrowserController(browser)

    await controller.close()

    assert browser.stop_calls == 0
    assert not controller.is_open


async def test_reopen_after_close_starts_a_fresh_lifecycle():
    browser = FakeBrowser()
    controller = BrowserController(browser)

    await controller.open()
    await controller.close()
    await controller.open()

    assert browser.start_calls == 2
    assert browser.stop_calls == 1
    assert controller.is_open


def test_ownership_defaults_to_managed():
    controller = BrowserController(FakeBrowser())
    assert controller.ownership is BrowserOwnership.MANAGED
    assert controller.owns_process is True


def test_ownership_reads_external_from_adapter():
    controller = BrowserController(FakeBrowser(ownership=BrowserOwnership.EXTERNAL))
    assert controller.ownership is BrowserOwnership.EXTERNAL
    assert controller.owns_process is False


async def test_external_close_delegates_to_adapter_stop_only():
    # For an EXTERNAL adapter, close() drives the adapter's stop() — which is a
    # DISCONNECT that never closes the operator's process. The controller adds no
    # separate process-close call.
    browser = FakeBrowser(ownership=BrowserOwnership.EXTERNAL)
    controller = BrowserController(browser)
    await controller.open()
    await controller.close()
    assert browser.stop_calls == 1
    assert not controller.is_open


async def test_failed_close_clears_open_flag_and_propagates():
    # A stop() error must not leave the controller stuck 'open' — otherwise a
    # retry would no-op and the browser could never be closed. The error still
    # surfaces to the caller.
    browser = FakeBrowser(fail_stop=True)
    controller = BrowserController(browser)
    await controller.open()

    with pytest.raises(RuntimeError, match="stop failed"):
        await controller.close()

    assert not controller.is_open
