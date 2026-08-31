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


def run_autoplay_loop(clicker, get_attrition, x: float, y: float, *,
                      max_attrition: int, max_clicks: int = 500, key: str | None = "r",
                      interval: float = 0.15, sleep=time.sleep,
                      should_stop=None) -> AutoplayResult:
    """Fight at (x, y) while the player's attrition stays below ``max_attrition``.

    Before each fight the current attrition is read via ``get_attrition()``:
    - ``>= max_attrition`` → STOP (never fights at/over the limit, so it never pushes past
      it); with a per-fight +1 step this makes ``max_attrition`` a hard ceiling.
    - ``None`` (unknown) → STOP — fail-safe, never fight blind (matches the gate invariant).
    ``max_clicks`` is a hard pojistka. ``sleep`` must pump live events in the real run."""
    fights = 0
    reason = "max_clicks"
    for _ in range(max(0, max_clicks)):
        if should_stop is not None and should_stop():
            reason = "stopped"
            break
        a = get_attrition()
        if a is None:
            reason = "attrition_unknown"
            break
        if a >= max_attrition:
            reason = "attrition_limit"
            break
        clicker.click_xy(x, y)
        fights += 1
        if key:
            sleep(interval)
            clicker.press(key)
        sleep(interval)
    final = None
    try:
        final = get_attrition()
    except Exception:
        pass
    return AutoplayResult(fights=fights, final_attrition=final, reason=reason)


def run_autoplay(endpoint: str, x: float, y: float, *, max_attrition: int,
                 max_clicks: int = 500, key: str | None = "r", interval: float = 0.15,
                 index=None, match=None, connect=None,
                 startup_timeout_s: float = 20.0) -> AutoplayResult:  # pragma: no cover - live
    """Connect over CDP, wire the `/game/json` reader + clicker on the chosen tab, wait for
    the first attrition reading, then run the gated loop. Read+act on one connection."""
    def _go(browser) -> AutoplayResult:
        page = _select_page(browser, index=index, match=match)
        try:
            page.bring_to_front()
        except Exception:
            pass
        reader = LiveGbgReader()
        # feed the reader from this tab's /game/json responses
        handler = make_response_handler(reader)
        page.on("response", lambda resp: handler(resp)
                if "/game/json" in getattr(resp, "url", "") else None)

        def _wait(ms):  # pump Playwright events (so responses arrive) while pacing
            page.wait_for_timeout(ms * 1000)

        def _attrition():
            bg = reader.snapshot
            return bg.player.attrition_level if bg and bg.player else None

        print(f"Target tab: {page.url}", flush=True)
        print("Waiting for the first attrition reading… "
              "(fight once or open GBG so the game sends state)", flush=True)
        deadline = time.time() + startup_timeout_s
        while _attrition() is None and time.time() < deadline:
            page.wait_for_timeout(500)
        if _attrition() is None:
            return AutoplayResult(0, None, "attrition_unknown")
        print(f"Attrition now {_attrition()}, limit {max_attrition}. Fighting…", flush=True)
        return run_autoplay_loop(CdpClicker(page), _attrition, x, y,
                                 max_attrition=max_attrition, max_clicks=max_clicks,
                                 key=key, interval=interval, sleep=_wait)

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
                         max_clicks=args.max_clicks, key=args.key, interval=args.interval,
                         index=args.tab_index, match=args.tab)
        print(f"stopped — {r.fights} fight(s), attrition {r.final_attrition}, reason: {r.reason}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Autoplay failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
