"""Gated autoplay — fight (click + repeat key) until the player's attrition reaches a limit.

This joins the two halves: the **brain** (live `/game/json` reader → the player's
`attrition_level`) and the **hand** (CDP click on the fight button). The safety gate is the
project invariant made concrete: **before every fight, read the current attrition; if it has
reached the limit, STOP.** A province runs out of fights on its own; attrition is the ceiling.

Layers, separated for testability:

- :func:`run_autoplay_loop` — pure loop. Given a clicker and a ``get_attrition()`` callable,
  it fights while attrition is below the limit, with a hard ``max_clicks`` cap and an
  ``attrition-unknown → stop`` fail-safe. Fully unit-tested, no browser.
- :func:`run_autoplay` / :func:`main` — live glue: one CDP connection carrying both the
  `/game/json` reader (attrition source) and the clicker, on the chosen tab. ``no-cover``.

Explicit, opt-in, gated. Not part of the observe-only app.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from bap.forge.action.cdp_click import CdpClicker, _select_page  # noqa: F401
from bap.forge.gbg_data.live import LiveGbgReader, make_response_handler

logger = logging.getLogger("bap.forge.action.autoplay")


@dataclass(frozen=True)
class AutoplayResult:
    fights: int
    final_attrition: int | None
    reason: str          # "attrition_limit" | "attrition_unknown" | "max_clicks" | "stopped"


def _effective_attrition(live, start_attrition, fights):
    """The attrition we gate on: the live reading and the locally-counted value
    (``start + fights``, since attrition rises +1 per fight), whichever is higher — so a
    missing live feed still gates, and a faster-than-expected live value wins. ``None`` only
    when we have neither."""
    counted = None if start_attrition is None else start_attrition + fights
    if live is None:
        return counted
    if counted is None:
        return live
    return max(live, counted)


def run_autoplay_loop(clicker, get_attrition, x: float, y: float, *,
                      max_attrition: int, start_attrition: int | None = None,
                      max_clicks: int = 500, key: str | None = "r",
                      interval: float = 0.15, sleep=time.sleep,
                      should_stop=None) -> AutoplayResult:
    """Fight at (x, y) while attrition stays below ``max_attrition``.

    Attrition is tracked two ways and the **higher** gates (see :func:`_effective_attrition`):
    a live reading from ``get_attrition()`` (may be ``None`` if the game hasn't sent state),
    and a local count from ``start_attrition`` (+1 per fight). Before each fight:
    - effective ``>= max_attrition`` → STOP (never fights at/over the limit → hard ceiling);
    - effective ``None`` (no baseline *and* no live data) → STOP — fail-safe, never blind.
    ``max_clicks`` is a hard pojistka. ``sleep`` must pump live events in the real run."""
    fights = 0
    reason = "max_clicks"
    effective = _effective_attrition(None, start_attrition, 0)
    for _ in range(max(0, max_clicks)):
        if should_stop is not None and should_stop():
            reason = "stopped"
            break
        effective = _effective_attrition(get_attrition(), start_attrition, fights)
        if effective is None:
            reason = "attrition_unknown"
            break
        if effective >= max_attrition:
            reason = "attrition_limit"
            break
        clicker.click_xy(x, y)
        fights += 1
        if key:
            sleep(interval)
            clicker.press(key)
        sleep(interval)
    return AutoplayResult(fights=fights, final_attrition=effective, reason=reason)


def run_autoplay(endpoint: str, x: float, y: float, *, max_attrition: int,
                 start_attrition: int | None = None, max_clicks: int = 500,
                 key: str | None = "r", interval: float = 0.15,
                 index=None, match=None, connect=None,
                 startup_timeout_s: float = 8.0) -> AutoplayResult:  # pragma: no cover - live
    """Connect over CDP, wire the `/game/json` reader + clicker on the chosen tab, and run the
    gated loop. If ``start_attrition`` is given, the loop counts locally from it and starts
    immediately (live data only corrects); otherwise it briefly waits for a live baseline."""
    def _go(browser) -> AutoplayResult:
        page = _select_page(browser, index=index, match=match)
        try:
            page.bring_to_front()
        except Exception:
            pass
        reader = LiveGbgReader()
        handler = make_response_handler(reader)
        page.on("response", lambda resp: handler(resp)
                if "/game/json" in getattr(resp, "url", "") else None)

        def _wait(ms):  # pump Playwright events (so live responses arrive) while pacing
            page.wait_for_timeout(ms * 1000)

        def _attrition():
            bg = reader.snapshot
            return bg.player.attrition_level if bg and bg.player else None

        print(f"Target tab: {page.url}", flush=True)
        if start_attrition is None:
            # no baseline given — briefly hope the game sends state (open GBG to trigger it)
            print("No --attrition-now given; waiting briefly for the game to send state…",
                  flush=True)
            deadline = time.time() + startup_timeout_s
            while _attrition() is None and time.time() < deadline:
                page.wait_for_timeout(500)
            if _attrition() is None:
                print("No attrition data arrived. Re-run with --attrition-now N "
                      "(your current attrition) so it can count locally.", flush=True)
                return AutoplayResult(0, None, "attrition_unknown")
        eff0 = _effective_attrition(_attrition(), start_attrition, 0)
        print(f"Starting attrition {eff0}, limit {max_attrition}. Fighting…", flush=True)
        return run_autoplay_loop(CdpClicker(page), _attrition, x, y,
                                 max_attrition=max_attrition, start_attrition=start_attrition,
                                 max_clicks=max_clicks, key=key, interval=interval, sleep=_wait)

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap = argparse.ArgumentParser(
        prog="bap-forge-autoplay",
        description="Fight on a Forge tab until attrition reaches a limit (CDP, gated).")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="target tab: url/title contains this text")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index",
                    help="target tab by index (see 'bap-forge-click --list')")
    ap.add_argument("--x", type=float, required=True, help="fight-button viewport X (CSS px)")
    ap.add_argument("--y", type=float, required=True, help="fight-button viewport Y (CSS px)")
    ap.add_argument("--max-attrition", type=int, required=True, dest="max_attrition",
                    help="stop when the player's attrition reaches this")
    ap.add_argument("--attrition-now", type=int, default=None, dest="attrition_now",
                    help="your current attrition (baseline for local counting; recommended)")
    ap.add_argument("--max-clicks", type=int, default=500, dest="max_clicks",
                    help="hard safety cap on fights (default 500)")
    ap.add_argument("--key", default="r", help="repeat key pressed after each click (default r)")
    ap.add_argument("--interval", type=float, default=0.15, help="seconds between actions")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args(argv)

    print(f"Autoplay on {args.cdp} tab={args.tab or args.tab_index}: fight at "
          f"({args.x}, {args.y}) + '{args.key}' until attrition >= {args.max_attrition} "
          f"(hard cap {args.max_clicks} fights).")
    if not args.yes:
        try:
            if input("This will fight the live game automatically. Type 'yes': ").strip() != "yes":
                print("aborted."); return 1
        except EOFError:
            print("no confirmation (non-interactive) — pass --yes."); return 1
    try:
        r = run_autoplay(args.cdp, args.x, args.y, max_attrition=args.max_attrition,
                         start_attrition=args.attrition_now, max_clicks=args.max_clicks,
                         key=args.key, interval=args.interval,
                         index=args.tab_index, match=args.tab)
        print(f"stopped — {r.fights} fight(s), attrition {r.final_attrition}, reason: {r.reason}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Autoplay failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
