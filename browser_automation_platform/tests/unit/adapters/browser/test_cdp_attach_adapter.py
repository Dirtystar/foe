"""External-Chrome CDP attach adapter (Milestone 4.16) — observe-only guest.

Uses a faithful fake CDP endpoint (no real Chrome): a stand-in "Chrome process"
that stays alive across connect/disconnect, so the tests prove the critical
guarantee — BAP attaches and detaches but NEVER closes the operator's browser.
"""

from __future__ import annotations

import json

import pytest

from bap.core.domain.enums import BrowserOwnership
from bap.core.ports.browser_port import (
    BrowserManagerError,
    BrowserNotStartedError,
    TabHandle,
    TabProfile,
)
from bap.adapters.browser.cdp_attach_adapter import (
    CdpAttachBrowserManager,
    CdpConnectionError,
    is_localhost_endpoint,
    normalize_endpoint,
    probe_cdp,
)


class FakePage:
    def __init__(self, url, title="tab"):
        self._url = url
        self._title = title
        self._closed = False

    @property
    def url(self):
        return self._url

    def is_closed(self):
        return self._closed

    async def title(self):
        return self._title

    def close(self):
        self._closed = True


class FakeContext:
    def __init__(self, pages):
        self.pages = pages


class FakeCdpBrowser:
    """What connect_over_cdp returns — a client connection to the real Chrome."""

    def __init__(self, chrome):
        self._chrome = chrome
        self.contexts = [FakeContext(chrome.pages)]

    async def close(self):
        # For a connect_over_cdp browser, close() drops the CDP client only.
        self._chrome.connections -= 1  # the operator's Chrome keeps running


class FakeChrome:
    """Stands in for the operator-launched Chrome process. `alive` must stay True
    through every attach/detach — BAP never kills it."""

    def __init__(self, pages, *, fail_connect=False):
        self.pages = pages
        self.alive = True
        self.connections = 0
        self.fail_connect = fail_connect

    def connector(self):
        async def _connect(endpoint):
            if self.fail_connect:
                raise ConnectionRefusedError("connection refused")
            if not self.alive:
                raise ConnectionRefusedError("Chrome not running")
            self.connections += 1
            return FakeCdpBrowser(self)

        return _connect


def _chrome():
    return FakeChrome([
        FakePage("https://cz8.forgeofempires.com/game/index", "Forge H"),
        FakePage("https://mail.example.com/inbox", "Email"),
    ])


def test_ownership_is_external():
    adapter = CdpAttachBrowserManager("http://127.0.0.1:9222")
    assert adapter.ownership is BrowserOwnership.EXTERNAL


async def test_attach_connects_without_launching_and_leaves_chrome_alive():
    chrome = _chrome()
    adapter = CdpAttachBrowserManager("127.0.0.1:9222", connect=chrome.connector())
    await adapter.start()
    assert adapter.connected is True
    assert chrome.connections == 1
    assert chrome.alive is True                    # BAP never launched/owns it


async def test_discovery_lists_all_open_tabs():
    chrome = _chrome()
    adapter = CdpAttachBrowserManager(connect=chrome.connector())
    await adapter.start()
    tabs = await adapter.scan_tabs()
    urls = {t.url for t in tabs}
    assert urls == {"https://cz8.forgeofempires.com/game/index", "https://mail.example.com/inbox"}
    # Adopt returns a handle to the exact page.
    handle = await adapter.adopt_tab(tabs[0].tab_id)
    assert isinstance(handle, TabHandle)


async def test_disconnect_detaches_but_never_closes_chrome():
    chrome = _chrome()
    adapter = CdpAttachBrowserManager(connect=chrome.connector())
    await adapter.start()
    await adapter.stop()
    assert adapter.connected is False
    assert chrome.connections == 0                 # our CDP client disconnected
    assert chrome.alive is True                    # the operator's Chrome survives


async def test_stop_is_idempotent_and_scan_requires_attach():
    chrome = _chrome()
    adapter = CdpAttachBrowserManager(connect=chrome.connector())
    await adapter.stop()                           # not attached -> no-op
    with pytest.raises(BrowserNotStartedError):
        await adapter.scan_tabs()


async def test_failed_connection_is_recoverable():
    chrome = FakeChrome([], fail_connect=True)
    adapter = CdpAttachBrowserManager(connect=chrome.connector())
    with pytest.raises(CdpConnectionError):
        await adapter.start()
    assert adapter.connected is False              # clean, recoverable state
    # Operator launches Chrome; a retry now succeeds (no restart of BAP).
    chrome.fail_connect = False
    await adapter.start()
    assert adapter.connected is True


async def test_reconnect_after_chrome_restart():
    chrome = _chrome()
    adapter = CdpAttachBrowserManager(connect=chrome.connector())
    await adapter.start()
    await adapter.stop()
    # Operator restarts Chrome (new process, same endpoint).
    chrome2 = _chrome()
    adapter = CdpAttachBrowserManager(connect=chrome2.connector())
    await adapter.start()
    assert adapter.connected and chrome2.connections == 1


async def test_guest_never_opens_or_navigates_tabs():
    chrome = _chrome()
    adapter = CdpAttachBrowserManager(connect=chrome.connector())
    await adapter.start()
    with pytest.raises(BrowserManagerError):
        await adapter.open_tab(TabProfile(id="x"))
    tabs = await adapter.scan_tabs()
    handle = await adapter.adopt_tab(tabs[0].tab_id)
    # close_tab is a no-op — the operator owns the tab.
    assert await adapter.close_tab(handle) is None


# --- endpoint helpers + probe -------------------------------------------------

def test_normalize_and_localhost():
    assert normalize_endpoint("9222") == "http://127.0.0.1:9222"
    assert normalize_endpoint("127.0.0.1:9222") == "http://127.0.0.1:9222"
    assert normalize_endpoint("") == "http://127.0.0.1:9222"
    assert is_localhost_endpoint("http://127.0.0.1:9222") is True
    assert is_localhost_endpoint("http://10.0.0.5:9222") is False


def test_probe_reports_reachable_with_fake_fetch():
    pages = [
        {"type": "page", "url": "https://cz8.forgeofempires.com/game"},
        {"type": "page", "url": "https://news.example.com/"},
    ]

    def fake_fetch(url: str) -> bytes:
        if url.endswith("/json/version"):
            return json.dumps({"Browser": "Chrome/120.0"}).encode()
        if url.endswith("/json"):
            return json.dumps(pages).encode()
        raise AssertionError(url)

    out = probe_cdp("127.0.0.1:9222", fetch=fake_fetch)
    assert out["reachable"] is True
    assert out["browser"] == "Chrome/120.0"
    assert out["tabs"] == 2 and out["forge_tabs"] == 1
    assert out["localhost"] is True


def test_probe_unreachable_is_a_clean_result_not_an_exception():
    def refuse(url: str) -> bytes:
        raise ConnectionRefusedError("no chrome")

    out = probe_cdp("127.0.0.1:9222", fetch=refuse)
    assert out["reachable"] is False
    assert "error" in out
