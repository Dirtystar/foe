"""The only part that touches a browser: feed the engine from one world's ``/game/json``.

It attaches to the Chrome the player is already using (CDP), picks **one** tab — the watched
world, cz8 by default — and listens. It sends nothing to the game, clicks nothing, and reads
no other tab, so it can run happily beside the farmer (or beside a human just playing).

Where the snapshots come from: ``getBattleground`` fires whenever GBG is opened or the page is
refreshed while in GBG. One such snapshot already carries every opening for hours ahead, so
the alerter does not need its own refresh loop — it rides along on the entries that happen
anyway. ``--refresh-minutes`` exists for the case where nothing else is driving the tab: it
reloads the page on a timer, which re-fires the snapshot when the game returns to GBG.
"""

from __future__ import annotations

import logging
import time

from bap.alerting.engine import AlertEngine
from bap.forge.gbg_data.live import LiveGbgReader

logger = logging.getLogger("bap.alerting.watcher")

_DATA_URLS = ("/game/json", "/map/data")


def make_handler(reader: LiveGbgReader, engine: AlertEngine):
    """Playwright ``response`` handler: parse game data, hand new snapshots to the engine.
    Never raises — a body we cannot read is simply skipped."""
    def _handle(resp) -> None:
        try:
            url = getattr(resp, "url", "") or ""
            if not any(u in url for u in _DATA_URLS):
                return
            body = resp.text()
        except BaseException:          # includes CancelledError on a torn-down connection
            return
        if not reader.feed(body):
            return
        if reader.map_layout is not None:
            engine.on_layout(reader.map_layout)
        if reader.snapshot is not None:
            engine.on_snapshot(reader.snapshot)
    return _handle


def _select_world_page(browser, match: str):  # pragma: no cover - live glue
    pages = [p for ctx in browser.contexts for p in ctx.pages]
    hits = [p for p in pages if match.lower() in (getattr(p, "url", "") or "").lower()]
    if not hits:
        raise RuntimeError(
            f"no tab matching {match!r} — open that world in this Chrome first "
            f"({len(pages)} tab(s) seen)")
    return hits[0]


def run_watch(cfg, engine: AlertEngine | None, *, connect=None, endpoint: str = "",
              refresh_minutes: float = 0.0, once: bool = False, handler=None,
              on_status=None) -> int:  # pragma: no cover - needs a live browser
    """Attach to Chrome, watch the world's tab, and tick the engine forever (Ctrl-C to stop).

    ``handler`` overrides what happens to each response, and ``engine`` may then be ``None``:
    that is how ``bap-alert collect`` reuses this loop to forward snapshots to a scheduler
    instead of deciding anything itself.
    """
    reader = LiveGbgReader()
    if handler is None:
        handler = make_handler(reader, engine)
    endpoint = endpoint or cfg.cdp
    if not endpoint:
        from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

        endpoint = DEFAULT_CDP_ENDPOINT

    def _go(browser) -> int:
        page = _select_world_page(browser, cfg.tab_match)
        page.on("response", handler)
        logger.info("watching %s (%s)", cfg.world, getattr(page, "url", ""))
        next_refresh = time.time() + refresh_minutes * 60 if refresh_minutes else None
        try:
            while True:
                sent = engine.tick() if engine is not None else []
                if on_status is not None:
                    on_status(engine, sent)
                if once:
                    return 0
                if next_refresh and time.time() >= next_refresh:
                    next_refresh = time.time() + refresh_minutes * 60
                    try:
                        page.reload(wait_until="domcontentloaded")
                    except Exception as exc:            # noqa: BLE001
                        logger.warning("refresh failed: %s", exc)
                page.wait_for_timeout(int(cfg.poll_seconds * 1000))
        except KeyboardInterrupt:
            logger.info("stopped")
            return 0

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint)
        return _go(browser)


__all__ = ["make_handler", "run_watch"]
