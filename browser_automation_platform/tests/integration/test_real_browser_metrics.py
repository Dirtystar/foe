"""Optional integration: collect resource metrics from real Chromium.

Skipped by default. Run with:  pytest -m integration
Skips if the browser binary is unavailable.
"""

import os

import pytest

pytestmark = pytest.mark.integration

from bap.adapters.browser.playwright_adapter import PlaywrightBrowserManager
from bap.adapters.browser.playwright_metrics import PlaywrightBrowserMetrics
from bap.core.domain.models import TabProfile

_EXE = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH")
_PAGE = "data:text/html,<html><body><h1>metrics</h1></body></html>"


async def test_collect_metrics_from_real_chromium_and_close_cleanly():
    manager = PlaywrightBrowserManager(headless=True, max_tabs=4, executable_path=_EXE)
    try:
        await manager.start()
    except Exception as exc:
        pytest.skip(f"real browser unavailable: {exc}")

    metrics = PlaywrightBrowserMetrics(manager, browser_id="it")
    try:
        # empty browser: counts are zero-ish, collection never raises
        empty = await metrics.collect()
        assert empty.browser_id == "it"

        # open N tabs and confirm counts rise
        n = 3
        for i in range(n):
            await manager.open_tab(TabProfile(id=f"t{i}", start_url=_PAGE))

        snap = await metrics.collect()
        assert snap.pages >= n
        assert snap.contexts >= n  # isolated context per tab (default)
        # memory is best-effort; if present it must be a positive number
        if snap.memory_mb is not None:
            assert snap.memory_mb > 0
    finally:
        await manager.stop()

    # after shutdown, collection is safe and reports nothing open
    after = await metrics.collect()
    assert after.pages == 0
    assert after.contexts == 0
