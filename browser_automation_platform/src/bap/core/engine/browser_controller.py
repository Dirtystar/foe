"""BrowserController: sole owner of the browser's open/close lifecycle.

Automation lifecycle (start/stop ticking) and browser lifecycle (open/close the
window) are two independent things. Conflating them is what made "Stop" close
the browser. This controller isolates the browser lifecycle behind an
idempotent open/close, so the application layer can own it explicitly:

  - Open Browser / Close Browser are user-visible, deliberate actions.
  - Start / Stop drive automation only and never touch the browser.
  - Exit performs a full teardown (stop automation, then close the browser).

The SessionManager still uses the BrowserPort for per-tab operations
(open_tab / close_tab), but it no longer starts or stops the browser — that is
this controller's single responsibility. Idempotent by contract: open() while
open and close() while closed are both no-ops, so overlapping triggers collapse
into one clean transition.
"""

from __future__ import annotations

from bap.core.ports.browser_port import BrowserPort


class BrowserController:
    def __init__(self, browser: BrowserPort) -> None:
        self._browser = browser
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    async def open(self) -> None:
        """Open the browser window. No-op if already open."""
        if self._open:
            return
        await self._browser.start()
        self._open = True

    async def close(self) -> None:
        """Close the browser window. No-op if not open. The flag is cleared
        even if the underlying stop() raises, so a failed close never wedges
        the controller into a permanently-'open' state; the error propagates."""
        if not self._open:
            return
        try:
            await self._browser.stop()
        finally:
            self._open = False


__all__ = ["BrowserController"]
