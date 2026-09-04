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

from bap.core.domain.enums import BrowserOwnership
from bap.core.ports.browser_port import BrowserPort


class BrowserController:
    """Owns the browser's open/close (connect/disconnect) lifecycle.

    Ownership is not the controller's decision — it reads it from the adapter
    (``browser.ownership``). For a MANAGED adapter, ``close()`` tears the process
    down; for an EXTERNAL (CDP-attach) adapter, the adapter's ``stop()`` only
    disconnects the CDP client and never closes the operator's Chrome. Either
    way the controller drives the same idempotent open/close transitions — the
    behavioural difference lives entirely in the adapter, so there is no mutable
    flag here deciding whether a close kills the operator's browser.
    """

    def __init__(self, browser: BrowserPort) -> None:
        self._browser = browser
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def ownership(self) -> BrowserOwnership:
        """MANAGED or EXTERNAL, as declared by the adapter."""
        return getattr(self._browser, "ownership", BrowserOwnership.MANAGED)

    @property
    def owns_process(self) -> bool:
        """True when a close() tears down a BAP-owned process; False when the
        browser is operator-owned and close() only disconnects."""
        return self.ownership is BrowserOwnership.MANAGED

    async def open(self) -> None:
        """Open (MANAGED) or attach to (EXTERNAL) the browser. No-op if already open."""
        if self._open:
            return
        await self._browser.start()
        self._open = True

    async def close(self) -> None:
        """Close (MANAGED) or disconnect from (EXTERNAL) the browser. No-op if not
        open. The flag is cleared even if the underlying stop() raises, so a
        failed close never wedges the controller into a permanently-'open' state;
        the error propagates. In EXTERNAL mode the adapter's stop() disconnects
        only — the operator's Chrome process is never closed here."""
        if not self._open:
            return
        try:
            await self._browser.stop()
        finally:
            self._open = False


__all__ = ["BrowserController"]
