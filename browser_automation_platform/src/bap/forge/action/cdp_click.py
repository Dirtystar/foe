"""CDP-targeted clicking — click the game tab, not the desktop.

Unlike an OS autoclicker (which fires at the physical cursor and needs the window
foregrounded), this dispatches the click **into the attached tab's renderer** at a
viewport (CSS) coordinate over CDP. It does **not** move the real mouse and works on a
backgrounded tab. It's the actuation half of the data-driven flow: the data brain decides
*what* to hit, a calibrated fixed coordinate says *where* the action button is.

Layers, separated so the logic is testable without a browser:

- :class:`CdpClicker` — a thin wrapper over a Playwright ``page`` exposing exactly
  ``click_xy`` and ``press`` (one key). Nothing else — no drag, no typing.
- :func:`run_click_loop` — the pure loop (count / interval / optional repeat key / stop),
  driving any clicker. Fully unit-tested with a fake.
- :func:`connect_and_run` / :func:`main` — the Playwright/CDP wiring + CLI (needs a live
  browser; marked no-cover).

This is an **explicit, opt-in action tool** — invoked deliberately with coordinates, not
part of the observe-only app. Every action is logged.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("bap.forge.action")


class CdpClicker:
    """Click/keypress into one Playwright ``page`` via CDP (no OS cursor movement)."""

    def __init__(self, page) -> None:
        self._page = page

    def click_xy(self, x: float, y: float) -> None:
        """One left click at viewport CSS coordinate (x, y), dispatched to the tab."""
        self._page.mouse.click(x, y)
        logger.info("cdp_click", extra={"x": x, "y": y})

    def press(self, key: str) -> None:
        """Press one key (e.g. 'r' to repeat a fight), dispatched to the tab."""
        self._page.keyboard.press(key)
        logger.info("cdp_key", extra={"key": key})


def run_click_loop(clicker, x: float, y: float, *, key: str | None = None,
                   count: int = 1, interval: float = 0.15,
                   sleep=time.sleep, should_stop=None) -> int:
    """Click (x, y) ``count`` times, optionally pressing ``key`` after each click, pacing
    with ``interval`` seconds. Stops early if ``should_stop()`` returns True. Returns the
    number of clicks actually performed. Pure logic — ``sleep`` and ``should_stop`` are
    injectable so it is deterministic in tests."""
    done = 0
    for _ in range(max(0, count)):
        if should_stop is not None and should_stop():
            break
        clicker.click_xy(x, y)
        done += 1
        if key:
            sleep(interval)
            clicker.press(key)
        sleep(interval)
    return done


def _find_game_page(browser, host: str = "forgeofempires"):  # pragma: no cover - live glue
    for ctx in browser.contexts:
        for page in ctx.pages:
            try:
                if host in (page.url or ""):
                    return page
            except Exception:
                continue
    # fall back to the first page if the host wasn't matched
    for ctx in browser.contexts:
        if ctx.pages:
            return ctx.pages[0]
    return None


def connect_and_run(endpoint: str, x: float, y: float, *, key: str | None = None,
                    count: int = 1, interval: float = 0.15,
                    connect=None) -> int:  # pragma: no cover - needs a live browser
    """Connect to Chrome at ``endpoint`` over CDP, find the Forge page, and run the click
    loop on it. ``connect`` is injectable; by default uses Playwright ``connect_over_cdp``.
    Returns the number of clicks performed."""
    def _go(browser) -> int:
        page = _find_game_page(browser)
        if page is None:
            raise RuntimeError("no page found in the connected browser")
        logger.info("cdp_action_target", extra={"url": page.url, "x": x, "y": y,
                                                 "key": key, "count": count})
        return run_click_loop(CdpClicker(page), x, y, key=key, count=count, interval=interval)

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


_PROBE_JS = (
    "() => { if (window.__bapProbe) return; window.__bapProbe = 1;"
    " document.addEventListener('click',"
    " e => console.log('BAPCLICK ' + Math.round(e.clientX) + ' ' + Math.round(e.clientY)),"
    " true); }")


def probe_coordinate(endpoint: str, *, connect=None) -> int:  # pragma: no cover - live glue
    """Scan the fixed coordinate: on every Forge page, log the **viewport (CSS) coordinate**
    of each real click you make (via console, robust to page reloads), so you can read off
    the action button's fixed (x, y) and hardcode it. Read-only — it does not click."""
    def _on_console(msg) -> None:
        try:
            text = msg.text if hasattr(msg, "text") else str(msg)
            if text.startswith("BAPCLICK "):
                _, x, y = text.split()
                print(f"  → click at   --x {x} --y {y}", flush=True)
        except Exception:
            pass

    def _arm(page) -> None:
        try:
            page.on("console", _on_console)
            page.evaluate(_PROBE_JS)
        except Exception:
            pass  # a page that won't take the listener is skipped, not fatal

    def _go(browser) -> int:
        armed = False
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "forgeofempires" in (getattr(page, "url", "") or ""):
                    _arm(page); armed = True
            try:
                ctx.on("page", _arm)          # cover tabs opened later
            except Exception:
                pass
        if not armed:  # fall back to arming every page if host match found nothing
            for ctx in browser.contexts:
                for page in ctx.pages:
                    _arm(page)
        print("Click the action button in the game to read its coordinate (Ctrl-C to stop).",
              flush=True)
        try:
            while True:
                # survive a page/target closing or reloading — just keep waiting
                pages = [p for c in browser.contexts for p in c.pages]
                waited = False
                for p in pages:
                    try:
                        p.wait_for_timeout(1000); waited = True; break
                    except Exception:
                        continue
                if not waited:
                    time.sleep(1)
        except KeyboardInterrupt:
            return 0

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap = argparse.ArgumentParser(
        prog="bap-forge-click",
        description="CDP-targeted click on the Forge tab (does not move your mouse).")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--probe", action="store_true",
                    help="scan mode: print the viewport coordinate of each click you make")
    ap.add_argument("--x", type=float, help="viewport X (CSS px) to click")
    ap.add_argument("--y", type=float, help="viewport Y (CSS px) to click")
    ap.add_argument("--key", default=None, help="key to press after each click, e.g. r")
    ap.add_argument("--count", type=int, default=1, help="how many clicks (default 1)")
    ap.add_argument("--interval", type=float, default=0.15, help="seconds between actions")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args(argv)

    if args.probe:
        try:
            return probe_coordinate(args.cdp)
        except Exception as exc:  # noqa: BLE001
            print(f"Could not connect to Chrome at {args.cdp}: {exc}")
            return 1
    if args.x is None or args.y is None:
        ap.error("--x and --y are required (or use --probe to scan a coordinate)")

    plan = (f"CDP click at ({args.x}, {args.y})"
            + (f" + press '{args.key}'" if args.key else "")
            + f", {args.count}× every {args.interval}s, on {args.cdp}")
    print(plan)
    if args.count > 1 and not args.yes:
        try:
            if input("This will click the live game repeatedly. Type 'yes' to proceed: ").strip() != "yes":
                print("aborted."); return 1
        except EOFError:
            print("no confirmation (non-interactive) — pass --yes to run a loop."); return 1
    try:
        n = connect_and_run(args.cdp, args.x, args.y, key=args.key,
                            count=args.count, interval=args.interval)
        print(f"done — {n} click(s) dispatched.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Could not run CDP click on {args.cdp}: {exc}\n"
              "Start Chrome with --remote-debugging-port and open Forge first.")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
