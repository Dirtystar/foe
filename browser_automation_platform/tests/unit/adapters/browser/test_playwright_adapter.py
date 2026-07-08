from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bap.adapters.browser import playwright_adapter as pw_adapter_module
from bap.adapters.browser.playwright_adapter import PlaywrightBrowserManager
from bap.core.ports.browser_port import (
    BrowserNotStartedError,
    DuplicateTabError,
    TabLimitExceededError,
    TabNotFoundError,
    TabProfile,
)


@pytest.fixture
def fake_playwright(monkeypatch):
    page = AsyncMock(name="page")
    page.is_closed = MagicMock(return_value=False)

    context = AsyncMock(name="context")
    context.new_page = AsyncMock(return_value=page)

    browser = AsyncMock(name="browser")
    browser.new_context = AsyncMock(return_value=context)

    chromium = AsyncMock(name="chromium")
    chromium.launch = AsyncMock(return_value=browser)

    playwright_instance = MagicMock(name="playwright_instance")
    playwright_instance.chromium = chromium
    playwright_instance.stop = AsyncMock()

    playwright_cm = MagicMock(name="playwright_context_manager")
    playwright_cm.start = AsyncMock(return_value=playwright_instance)

    async_playwright_factory = MagicMock(return_value=playwright_cm)
    monkeypatch.setattr(pw_adapter_module, "async_playwright", async_playwright_factory)

    return SimpleNamespace(
        factory=async_playwright_factory,
        instance=playwright_instance,
        chromium=chromium,
        browser=browser,
        context=context,
        page=page,
    )


async def test_start_launches_browser_and_is_idempotent(fake_playwright):
    manager = PlaywrightBrowserManager()

    await manager.start()
    await manager.start()

    fake_playwright.factory.assert_called_once()
    fake_playwright.chromium.launch.assert_awaited_once_with(headless=False)


async def test_executable_path_is_forwarded_to_launch_when_set(fake_playwright):
    manager = PlaywrightBrowserManager(executable_path="/opt/pw/chrome")

    await manager.start()

    fake_playwright.chromium.launch.assert_awaited_once_with(
        headless=False, executable_path="/opt/pw/chrome"
    )


async def test_executable_path_omitted_when_not_set(fake_playwright):
    manager = PlaywrightBrowserManager()

    await manager.start()

    _, kwargs = fake_playwright.chromium.launch.await_args
    assert "executable_path" not in kwargs


async def test_open_tab_before_start_raises(fake_playwright):
    manager = PlaywrightBrowserManager()

    with pytest.raises(BrowserNotStartedError):
        await manager.open_tab(TabProfile(id="tab1"))


async def test_open_tab_creates_isolated_context_with_configured_viewport(fake_playwright):
    manager = PlaywrightBrowserManager(isolate_contexts_per_tab=True)
    await manager.start()

    handle = await manager.open_tab(TabProfile(id="tab1"))

    fake_playwright.browser.new_context.assert_awaited_once_with(
        viewport={"width": 1920, "height": 1080}
    )
    assert handle.tab_id == "tab1"
    assert handle.native is fake_playwright.page
    assert manager.list_tabs() == ["tab1"]


async def test_open_tab_navigates_to_start_url_when_given(fake_playwright):
    manager = PlaywrightBrowserManager()
    await manager.start()

    await manager.open_tab(TabProfile(id="tab1", start_url="https://example.com"))

    fake_playwright.page.goto.assert_awaited_once_with("https://example.com")


async def test_open_tab_without_start_url_does_not_navigate(fake_playwright):
    manager = PlaywrightBrowserManager()
    await manager.start()

    await manager.open_tab(TabProfile(id="tab1"))

    fake_playwright.page.goto.assert_not_awaited()


async def test_open_tab_shared_context_mode_reuses_single_context(fake_playwright):
    manager = PlaywrightBrowserManager(isolate_contexts_per_tab=False, max_tabs=8)
    await manager.start()

    fake_playwright.browser.new_context.assert_awaited_once()
    fake_playwright.browser.new_context.reset_mock()

    await manager.open_tab(TabProfile(id="tab1"))
    await manager.open_tab(TabProfile(id="tab2"))

    fake_playwright.browser.new_context.assert_not_awaited()
    assert fake_playwright.context.new_page.await_count == 2


async def test_open_tab_duplicate_id_raises(fake_playwright):
    manager = PlaywrightBrowserManager()
    await manager.start()
    await manager.open_tab(TabProfile(id="tab1"))

    with pytest.raises(DuplicateTabError):
        await manager.open_tab(TabProfile(id="tab1"))


async def test_open_tab_respects_max_tabs_limit(fake_playwright):
    manager = PlaywrightBrowserManager(max_tabs=2)
    await manager.start()
    await manager.open_tab(TabProfile(id="tab1"))
    await manager.open_tab(TabProfile(id="tab2"))

    with pytest.raises(TabLimitExceededError):
        await manager.open_tab(TabProfile(id="tab3"))


async def test_open_tab_closes_owned_context_when_navigation_fails(fake_playwright):
    manager = PlaywrightBrowserManager(isolate_contexts_per_tab=True)
    await manager.start()
    fake_playwright.page.goto.side_effect = RuntimeError("navigation failed")

    with pytest.raises(RuntimeError):
        await manager.open_tab(TabProfile(id="tab1", start_url="https://example.com"))

    fake_playwright.context.close.assert_awaited_once()
    assert manager.list_tabs() == []


async def test_navigate_existing_tab(fake_playwright):
    manager = PlaywrightBrowserManager()
    await manager.start()
    handle = await manager.open_tab(TabProfile(id="tab1"))
    fake_playwright.page.goto.reset_mock()

    await manager.navigate(handle, "https://example.com/next")

    fake_playwright.page.goto.assert_awaited_once_with("https://example.com/next")


async def test_navigate_unknown_tab_raises(fake_playwright):
    manager = PlaywrightBrowserManager()
    await manager.start()

    from bap.core.ports.browser_port import TabHandle

    with pytest.raises(TabNotFoundError):
        await manager.navigate(TabHandle(tab_id="missing", native=None), "https://example.com")


async def test_close_tab_removes_and_closes_owned_resources(fake_playwright):
    manager = PlaywrightBrowserManager(isolate_contexts_per_tab=True)
    await manager.start()
    handle = await manager.open_tab(TabProfile(id="tab1"))

    await manager.close_tab(handle)

    fake_playwright.page.close.assert_awaited_once()
    fake_playwright.context.close.assert_awaited_once()
    assert manager.list_tabs() == []


async def test_close_tab_in_shared_context_mode_keeps_context_open(fake_playwright):
    manager = PlaywrightBrowserManager(isolate_contexts_per_tab=False)
    await manager.start()
    handle = await manager.open_tab(TabProfile(id="tab1"))
    fake_playwright.context.close.reset_mock()

    await manager.close_tab(handle)

    fake_playwright.page.close.assert_awaited_once()
    fake_playwright.context.close.assert_not_awaited()


async def test_close_unknown_tab_raises(fake_playwright):
    manager = PlaywrightBrowserManager()
    await manager.start()

    from bap.core.ports.browser_port import TabHandle

    with pytest.raises(TabNotFoundError):
        await manager.close_tab(TabHandle(tab_id="missing", native=None))


async def test_stop_closes_all_tabs_and_the_browser(fake_playwright):
    manager = PlaywrightBrowserManager()
    await manager.start()
    await manager.open_tab(TabProfile(id="tab1"))
    await manager.open_tab(TabProfile(id="tab2"))

    await manager.stop()

    assert fake_playwright.page.close.await_count == 2
    fake_playwright.browser.close.assert_awaited_once()
    fake_playwright.instance.stop.assert_awaited_once()
    assert manager.list_tabs() == []


async def test_stop_when_never_started_is_a_no_op(fake_playwright):
    manager = PlaywrightBrowserManager()

    await manager.stop()

    fake_playwright.factory.assert_not_called()
