"""Attended-browser discovery contract.

In attended mode the user drives a real, visible browser — opening, logging
into, and navigating tabs themselves — and BAP *adopts* the tabs they choose
rather than opening its own and navigating to a configured URL. This port is
the core-side contract for that: list what's open, and hand back an opaque
TabHandle for a chosen tab so a session can run its normal tick loop on it.

Engine-agnostic by construction: it speaks only in `BrowserTab` (plain data)
and `TabHandle` (opaque). No Playwright types appear here or in any core code —
they stay inside the adapter that implements this port.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bap.core.domain.models import BrowserTab, TabHandle


@runtime_checkable
class TabSourcePort(Protocol):
    """A browser whose open tabs can be discovered and adopted."""

    async def scan_tabs(self) -> list[BrowserTab]:
        """Return the tabs currently open in the attended browser, each with a
        stable id, its title, and its URL."""
        ...

    async def adopt_tab(self, tab_id: str) -> TabHandle:
        """Return an opaque handle to the already-open tab with this id, so a
        session can capture and act on it. Raises if the tab is gone."""
        ...


__all__ = ["BrowserTab", "TabSourcePort"]
