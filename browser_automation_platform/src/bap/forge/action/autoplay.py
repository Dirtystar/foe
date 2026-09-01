"""Gated autoplay — fight (click + repeat key) until the player's **real** attrition reaches
a limit.

This joins the **brain** (live `/game/json` reader → the player's `attrition_level`) and the
**hand** (CDP click on the fight button). The gate is the project invariant made concrete:
**before every fight, read the current attrition; if it has reached the limit, STOP.**

Important domain fact (from the operator, who plays): **attrition is not the fight count.**
Fighting a province marked X% gives an X% *chance* of +1 attrition per fight — so a limit of
50 can mean hundreds of fights. The only correct gate is the **real** `attrition_level` read
live from the game; we never estimate it from the click count. If live attrition is not
available, the loop fail-safe stops rather than fight blind.

Layers, separated for testability:

- :func:`run_autoplay_loop` — pure loop over a ``get_attrition()`` callable (the live value).
  Fully unit-tested, no browser.
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
                      max_attrition: int, max_clicks: int = 1000, key: str | None = "r",
                      interval: float = 0.15, sleep=time.sleep,
                      should_stop=None) -> AutoplayResult:
    """Fight at (x, y) while the **live** attrition stays below ``max_attrition``.

    Before each fight the current attrition is read via ``get_attrition()`` (the real value
    from the game):
    - ``>= max_attrition`` → STOP (never fights at/over the limit);
    - ``None`` (no live reading) → STOP — fail-safe, never fight blind.
    ``max_clicks`` is a hard pojistka. ``sleep`` must pump live events in the real run so the
    reading refreshes between fights."""
    fights = 0
    reason = "max_clicks"
    att = None
    for _ in range(max(0, max_clicks)):
        if should_stop is not None and should_stop():
            reason = "stopped"
            break
        att = get_attrition()
        if att is None:
            reason = "attrition_unknown"
            break
        if att >= max_attrition:
            reason = "attrition_limit"
            break
        clicker.click_xy(x, y)
        fights += 1
        if key:
            sleep(interval)
            clicker.press(key)
        sleep(interval)
    return AutoplayResult(fights=fights, final_attrition=att, reason=reason)


def run_autoplay(endpoint: str, x: float, y: float, *, max_attrition: int,
                 max_clicks: int = 1000, key: str | None = "r", interval: float = 0.15,
                 index=None, match=None, debug: bool = False, connect=None,
                 startup_timeout_s: float = 12.0) -> AutoplayResult:  # pragma: no cover - live
    """Connect over CDP, wire the `/game/json` reader + clicker on the chosen tab, wait for the
    first real attrition reading, then run the gated loop. The live listener is essential —
    attrition can only come from the game. Read+act on one connection."""
    def _go(browser) -> AutoplayResult:
        page = _select_page(browser, index=index, match=match)
        try:
            page.bring_to_front()
        except Exception:
            pass

        reader = LiveGbgReader()
        feed = make_response_handler(reader)
        last = {"att": None, "methods": set()}

        def _resp(resp):   # best-effort; swallow BaseException (CancelledError on teardown)
            try:
                url = getattr(resp, "url", "") or ""
                if "/game/json" not in url:
                    return
                if debug:
                    try:
                        import json as _j
                        for r in _j.loads(resp.text()):
                            m = f"{r.get('requestClass')}.{r.get('requestMethod')}"
                            if m not in last["methods"]:
                                last["methods"].add(m)
                                print(f"    [debug] saw {m}", flush=True)
                    except BaseException:
                        pass
                feed(resp)
                a = reader.snapshot.player.attrition_level if reader.snapshot else None
                if a is not None and a != last["att"]:
                    last["att"] = a
                    print(f"    attrition → {a}", flush=True)
            except BaseException:
                pass
        page.on("response", _resp)

        def _wait(ms):
            page.wait_for_timeout(ms * 1000)

        def _attrition():
            bg = reader.snapshot
            return bg.player.attrition_level if bg and bg.player else None

        print(f"Target tab: {page.url}", flush=True)
        print("Waiting for the game to send attrition… (open/refresh GBG to trigger it)",
              flush=True)
        deadline = time.time() + startup_timeout_s
        while _attrition() is None and time.time() < deadline:
            page.wait_for_timeout(500)
        if _attrition() is None:
            print("No live attrition arrived — refusing to fight blind. Open the GBG map so "
                  "the game sends state, then re-run. (Use --debug to see what it sends.)",
                  flush=True)
            try:
                page.remove_listener("response", _resp)
            except Exception:
                pass
            return AutoplayResult(0, None, "attrition_unknown")
        print(f"Attrition now {_attrition()}, limit {max_attrition}. Fighting…", flush=True)
        try:
            return run_autoplay_loop(CdpClicker(page), _attrition, x, y,
                                     max_attrition=max_attrition, max_clicks=max_clicks,
                                     key=key, interval=interval, sleep=_wait)
        finally:
            try:
                page.remove_listener("response", _resp)
            except Exception:
                pass

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
        description="Fight on a Forge tab until the real attrition reaches a limit (CDP, gated).")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="target tab: url/title contains this text")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index",
                    help="target tab by index (see 'bap-forge-click --list')")
    ap.add_argument("--x", type=float, required=True, help="fight-button viewport X (CSS px)")
    ap.add_argument("--y", type=float, required=True, help="fight-button viewport Y (CSS px)")
    ap.add_argument("--max-attrition", type=int, required=True, dest="max_attrition",
                    help="stop when the real attrition reaches this")
    ap.add_argument("--max-clicks", type=int, default=1000, dest="max_clicks",
                    help="hard safety cap on fights (default 1000)")
    ap.add_argument("--key", default="r", help="repeat key pressed after each click (default r)")
    ap.add_argument("--interval", type=float, default=0.15, help="seconds between actions")
    ap.add_argument("--debug", action="store_true",
                    help="print the /game/json methods and attrition changes seen")
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
                         index=args.tab_index, match=args.tab, debug=args.debug)
        print(f"stopped — {r.fights} fight(s), attrition {r.final_attrition}, reason: {r.reason}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Autoplay failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
