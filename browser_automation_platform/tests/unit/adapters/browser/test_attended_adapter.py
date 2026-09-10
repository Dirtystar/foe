from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bap.adapters.browser import attended_adapter as mod
from bap.adapters.browser.attended_adapter import AttendedBrowserManager
from bap.core.ports.browser_port import BrowserNotStartedError, TabNotFoundError


def _page(url, title="", closed=False):
    p = MagicMock(name=f"page:{url}")
    p.url = url
    p.is_closed = MagicMock(return_value=closed)
    p.title = AsyncMock(return_value=title)
    p.goto = AsyncMock()
    p.close = AsyncMock()
    return p


@pytest.fixture
def fake_pw(monkeypatch):
    pages = [_page("https://a.example/", "Alpha"), _page("https://b.example/", "Bravo")]
    context = AsyncMock(name="context")
    context.pages = pages
    context.new_page = AsyncMock(return_value=_page("about:blank", "New"))
    context.close = AsyncMock()

    instance = MagicMock(name="pw")
    instance.chromium = MagicMock()
    instance.chromium.launch_persistent_context = AsyncMock(return_value=context)
    instance.stop = AsyncMock()

    cm = MagicMock()
    cm.start = AsyncMock(return_value=instance)
    monkeypatch.setattr(mod, "async_playwright", MagicMock(return_value=cm))
    return SimpleNamespace(instance=instance, context=context, pages=pages)


async def test_start_launches_persistent_context(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path / "profile"))
    await mgr.start()
    fake_pw.instance.chromium.launch_persistent_context.assert_awaited_once()
    args, kwargs = fake_pw.instance.chromium.launch_persistent_context.call_args
    assert args[0] == str(tmp_path / "profile")
    assert kwargs["headless"] is False  # attended browser must be visible


async def test_scan_before_start_raises(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    with pytest.raises(BrowserNotStartedError):
        await mgr.scan_tabs()


async def test_scan_returns_title_url_and_id(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.start()
    tabs = await mgr.scan_tabs()
    assert [t.title for t in tabs] == ["Alpha", "Bravo"]
    assert [t.url for t in tabs] == ["https://a.example/", "https://b.example/"]
    assert all(t.tab_id for t in tabs)
    assert len({t.tab_id for t in tabs}) == 2  # unique ids


async def test_scan_falls_back_to_url_when_title_unavailable(fake_pw, tmp_path):
    fake_pw.pages[0].title = AsyncMock(side_effect=RuntimeError("navigating"))
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.start()
    tabs = await mgr.scan_tabs()
    assert tabs[0].title == "https://a.example/"  # falls back to URL


async def test_ids_are_stable_across_scans(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.start()
    first = {t.url: t.tab_id for t in await mgr.scan_tabs()}
    second = {t.url: t.tab_id for t in await mgr.scan_tabs()}
    assert first == second  # a given tab keeps its id


async def test_adopt_returns_handle_to_the_same_page(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.start()
    tabs = await mgr.scan_tabs()
    handle = await mgr.adopt_tab(tabs[0].tab_id)
    assert handle.tab_id == tabs[0].tab_id
    assert handle.native is fake_pw.pages[0]


async def test_adopt_unknown_or_closed_raises(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.start()
    with pytest.raises(TabNotFoundError):
        await mgr.adopt_tab("tab-999")

    tabs = await mgr.scan_tabs()
    fake_pw.pages[0].is_closed = MagicMock(return_value=True)  # user closed it
    with pytest.raises(TabNotFoundError):
        await mgr.adopt_tab(tabs[0].tab_id)


async def test_close_tab_does_not_close_the_users_page(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.start()
    tabs = await mgr.scan_tabs()
    handle = await mgr.adopt_tab(tabs[0].tab_id)
    await mgr.close_tab(handle)
    fake_pw.pages[0].close.assert_not_awaited()  # user tab left open


async def test_stop_closes_context_and_driver(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.start()
    await mgr.stop()
    fake_pw.context.close.assert_awaited_once()
    fake_pw.instance.stop.assert_awaited_once()


async def test_stop_when_never_started_is_a_noop(fake_pw, tmp_path):
    mgr = AttendedBrowserManager(user_data_dir=str(tmp_path))
    await mgr.stop()
    fake_pw.instance.stop.assert_not_awaited()
