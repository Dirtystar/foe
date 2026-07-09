"""Playwright-backed BrowserMetricsPort.

Page/context counts come from the PlaywrightBrowserManager (reliable).
Process memory/CPU are best-effort via psutil over the Chromium process tree
launched under this process — None when psutil is unavailable or no matching
process is found, so a missing process is handled safely rather than raising.
Keeps all Playwright/OS specifics inside the adapter layer.
"""

from __future__ import annotations

import logging
import os

from bap.adapters.browser.playwright_adapter import PlaywrightBrowserManager
from bap.core.ports.browser_metrics_port import BrowserMetricsPort, BrowserResourceSnapshot

logger = logging.getLogger(__name__)

_CHROMIUM_HINTS = ("chrome", "chromium", "headless_shell")


def _chromium_process_tree_stats() -> tuple[float | None, float | None]:
    """(memory_mb, cpu_percent) summed over Chromium descendants, or (None,
    None) if psutil is unavailable or no such process is found."""
    try:
        import psutil
    except ImportError:
        return (None, None)

    try:
        me = psutil.Process(os.getpid())
        procs = [
            p
            for p in me.children(recursive=True)
            if any(hint in (p.name() or "").lower() for hint in _CHROMIUM_HINTS)
        ]
    except Exception:
        return (None, None)
    if not procs:
        return (None, None)

    total_rss = 0
    total_cpu = 0.0
    for p in procs:
        try:
            total_rss += p.memory_info().rss
            total_cpu += p.cpu_percent(interval=None)
        except Exception:
            continue  # process vanished mid-collection; skip it
    return (total_rss / (1024 * 1024), total_cpu)


class PlaywrightBrowserMetrics(BrowserMetricsPort):
    def __init__(self, manager: PlaywrightBrowserManager, *, browser_id: str = "browser") -> None:
        self._manager = manager
        self._browser_id = browser_id

    async def collect(self) -> BrowserResourceSnapshot:
        contexts, pages = self._manager.context_and_page_counts()
        memory_mb, cpu_percent = _chromium_process_tree_stats()
        return BrowserResourceSnapshot(
            browser_id=self._browser_id,
            pages=pages,
            contexts=contexts,
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
        )


__all__ = ["PlaywrightBrowserMetrics"]
