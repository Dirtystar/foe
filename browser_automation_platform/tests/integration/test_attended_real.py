"""Optional integration: attended tab discovery + adoption on real Chromium.

Skipped by default. Run with:  pytest -m integration
Uses a headless persistent context (no display needed in CI); production runs
headed so the user can drive it.
"""

import os

import pytest

pytestmark = pytest.mark.integration

from bap.adapters.browser.attended_adapter import AttendedBrowserManager
from bap.core.domain.models import TabProfile
from bap.core.ports.browser_port import TabNotFoundError

_EXE = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH")
_ONE = "data:text/html,<title>One</title><body>one</body>"
_TWO = "data:text/html,<title>Two</title><body>two</body>"


async def test_scan_and_adopt_real_tabs(tmp_path):
    mgr = AttendedBrowserManager(
        user_data_dir=str(tmp_path / "profile"), headless=True, executable_path=_EXE
    )
    try:
        await mgr.start()
    except Exception as exc:
        pytest.skip(f"real browser unavailable: {exc}")

    try:
        # Simulate the user opening two pages in the attended window.
        await mgr.open_tab(TabProfile(id="p1", start_url=_ONE))
        await mgr.open_tab(TabProfile(id="p2", start_url=_TWO))

        tabs = await mgr.scan_tabs()
        by_title = {t.title: t for t in tabs}
        assert "One" in by_title and "Two" in by_title
        assert by_title["One"].url.startswith("data:text/html")

        # Adopt a chosen tab and confirm the handle points at the real page.
        handle = await mgr.adopt_tab(by_title["Two"].tab_id)
        assert await handle.native.title() == "Two"

        # Ids are stable across a re-scan.
        again = {t.title: t.tab_id for t in await mgr.scan_tabs()}
        assert again["One"] == by_title["One"].tab_id

        # A bogus id is rejected.
        with pytest.raises(TabNotFoundError):
            await mgr.adopt_tab("tab-does-not-exist")
    finally:
        await mgr.stop()
