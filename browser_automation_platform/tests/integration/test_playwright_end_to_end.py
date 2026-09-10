"""Optional integration test: real Chromium via Playwright.

Skipped by default. Run explicitly with:  pytest -m integration
Requires a Playwright browser to be installed. Uses a data: URL so it needs
no network.
"""

import os

import pytest

from bap.adapters.actions.playwright_action_handlers import ClickHandler
from bap.adapters.browser.playwright_adapter import PlaywrightBrowserManager
from bap.adapters.capture.playwright_capture import PlaywrightCaptureAdapter
from bap.core.domain.models import ActionRequest, Rect, Selector, TabProfile
from bap.core.ports.action_handler_port import ActionContext, ActionStatus

pytestmark = pytest.mark.integration

PAGE = "data:text/html,<html><body><button id='go'>Go</button><h1>Hi</h1></body></html>"


@pytest.fixture
async def browser():
    manager = PlaywrightBrowserManager(
        headless=True,
        max_tabs=2,
        executable_path=os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH"),
    )
    try:
        await manager.start()
    except Exception as exc:  # no browser binary available
        pytest.skip(f"Playwright browser unavailable: {exc}")
    yield manager
    await manager.stop()


async def test_open_capture_and_click(browser):
    tab = await browser.open_tab(TabProfile(id="t1", start_url=PAGE))
    capture = PlaywrightCaptureAdapter()

    full = await capture.capture(tab)
    assert full.width > 0 and full.height > 0
    assert full.data[:8] == b"\x89PNG\r\n\x1a\n"

    region = await capture.capture(tab, Rect(x=0, y=0, w=50, h=30))
    assert region.width == 50 and region.height == 30

    element = await capture.capture(tab, Selector(css="#go"))
    assert element.selector == "#go"

    result = await ClickHandler().execute(
        ActionRequest(action_type="click", params={"selector": "#go"}),
        ActionContext(tab=tab, profile_id="p1"),
    )
    assert result.status is ActionStatus.SUCCEEDED
