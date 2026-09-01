"""Round-robin autoplay across several worlds — fight each to its own attrition limit.

The all-day shape: a list of worlds, each with its own tab, fight-button point, and
**max attrition**. The scheduler rotates: on each world it reads the real live attrition,
fights a short **burst**, then moves on — so no world starves. When a world reaches its
limit it is marked **Done** and left alone; the rest keep going until every world is Done
(or the user stops). ``max_attrition`` of a very large number (e.g. 99999) means "no limit".

Layers, separated for testability:

- :func:`run_round_robin` — the pure scheduler over ``fight_once`` / ``get_attrition``
  callables. Fully unit-tested, no browser.
- :func:`load_world_plans` — read the per-world config (the shape the future GUI writes).
- :func:`run_round_robin_live` / :func:`main` — CDP glue + CLI. ``no-cover``.

Explicit, opt-in, gated per world by the real attrition. Fail-safe: a world with no live
attrition is skipped, never fought blind.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("bap.forge.action.round_robin")

UNLIMITED = 99999


@dataclass(frozen=True)
class WorldPlan:
    name: str
    x: float
    y: float
    max_attrition: int = UNLIMITED
    tab: str | None = None
    tab_index: int | None = None
    key: str | None = "r"


@dataclass
class WorldStatus:
    name: str
    fights: int = 0
    attrition: int | None = None
    done: bool = False
    reason: str = ""


def run_round_robin(worlds, fight_once, get_attrition, *, burst: int = 25,
                    max_total_fights: int = 1_000_000, sleep=time.sleep,
                    should_stop=None, on_event=None) -> dict:
    """Rotate over ``worlds``, fighting each in bursts until it reaches ``max_attrition``.

    ``fight_once(world)`` performs one fight; ``get_attrition(world)`` returns that world's
    current live attrition (``None`` if unknown). A world at/over its limit → **Done**; a
    world with unknown attrition is **skipped** (never fought blind). Stops when every world
    is Done, ``should_stop()`` is true, ``max_total_fights`` is hit, or a full rotation makes
    no progress (nothing has data). Returns ``{name: WorldStatus}``."""
    status = {w.name: WorldStatus(w.name) for w in worlds}
    total = 0

    def emit(kind, w):
        if on_event is not None:
            on_event(kind, w, status[w.name])

    def _stop():
        return should_stop is not None and should_stop()

    while True:
        if _stop():
            break
        pending = [w for w in worlds if not status[w.name].done]
        if not pending:
            break
        progressed = False
        for w in pending:
            if _stop():
                break
            st = status[w.name]
            a = get_attrition(w)
            st.attrition = a
            if a is not None and a >= w.max_attrition:
                st.done = True
                st.reason = "attrition_limit"
                emit("done", w)
                continue
            if a is None:
                emit("skip", w)      # no data yet — try again next rotation
                continue
            for _ in range(burst):
                if _stop():
                    break
                a = get_attrition(w)
                st.attrition = a
                if a is None:
                    break
                if a >= w.max_attrition:
                    st.done = True
                    st.reason = "attrition_limit"
                    emit("done", w)
                    break
                fight_once(w)
                st.fights += 1
                total += 1
                progressed = True
                if total >= max_total_fights:
                    break
            emit("burst", w)
            if total >= max_total_fights:
                break
        if total >= max_total_fights:
            for st in status.values():
                if not st.done:
                    st.reason = st.reason or "max_total_fights"
            break
        if not progressed:
            for st in status.values():
                if not st.done:
                    st.reason = st.reason or "no_data"
            break
    return status


def _loads_lenient(text: str):
    """json.loads, but tolerant of a common hand-edit slip: trailing commas before a
    closing } or ]. (A GUI will remove the need to hand-edit; until then, be forgiving.)"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


def load_world_plans(path) -> list:
    """Read `{"worlds": [{name, x, y, max_attrition?, tab?, tab_index?, key?}, …]}`."""
    data = _loads_lenient(Path(path).read_text(encoding="utf-8"))
    out = []
    for w in data.get("worlds", []):
        out.append(WorldPlan(
            name=str(w["name"]), x=float(w["x"]), y=float(w["y"]),
            max_attrition=int(w.get("max_attrition", UNLIMITED)),
            tab=w.get("tab"), tab_index=w.get("tab_index"),
            key=w.get("key", "r")))
    if not out:
        raise ValueError("config has no worlds")
    return out


def run_round_robin_live(endpoint, worlds, *, burst=25, interval=0.15,
                         startup_timeout_s=12.0, connect=None):  # pragma: no cover - live
    """Rotate the fight loop across the configured world tabs on one CDP connection. Each
    world gets its own `/game/json` reader (attrition source) and is brought to front when
    fought. Returns ``{name: WorldStatus}``."""
    from bap.forge.action.cdp_click import CdpClicker, _select_page
    from bap.forge.gbg_data.live import LiveGbgReader, make_response_handler

    def _go(browser):
        pages, readers, clickers = {}, {}, {}
        for w in worlds:
            page = _select_page(browser, index=w.tab_index, match=(w.tab or w.name))
            reader = LiveGbgReader()
            feed = make_response_handler(reader)

            def _mk(feed):
                def _resp(resp):
                    try:
                        if "/game/json" in (getattr(resp, "url", "") or ""):
                            feed(resp)
                    except BaseException:
                        pass
                return _resp
            page.on("response", _mk(feed))
            pages[w.name] = page
            readers[w.name] = reader
            clickers[w.name] = CdpClicker(page)
            print(f"world {w.name}: {page.url}  (limit "
                  f"{'∞' if w.max_attrition >= UNLIMITED else w.max_attrition})", flush=True)

        # try to get an initial attrition per world (open GBG map to trigger getBattleground)
        print("Reading initial attrition (make sure each world is on its GBG map)…", flush=True)
        deadline = time.time() + startup_timeout_s
        while time.time() < deadline and any(readers[w.name].attrition_level is None for w in worlds):
            for w in worlds:
                try:
                    pages[w.name].wait_for_timeout(300)
                except Exception:
                    pass

        def _attrition(w):
            return readers[w.name].attrition_level

        def _fight_once(w):
            page = pages[w.name]
            try:
                page.bring_to_front()
            except Exception:
                pass
            clickers[w.name].click_xy(w.x, w.y)
            if w.key:
                page.wait_for_timeout(int(interval * 1000))
                clickers[w.name].press(w.key)
            page.wait_for_timeout(int(interval * 1000))

        def _on_event(kind, w, st):
            if kind == "done":
                print(f"  ✅ Done {w.name} — attrition {st.attrition} (fought {st.fights})", flush=True)
            elif kind == "burst":
                print(f"  {w.name}: fought {st.fights}, attrition {st.attrition}", flush=True)
            elif kind == "skip":
                print(f"  {w.name}: no attrition data yet — open its GBG map. Skipping.", flush=True)

        return run_round_robin(worlds, _fight_once, _attrition, burst=burst,
                               on_event=_on_event)

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap = argparse.ArgumentParser(
        prog="bap-forge-farm",
        description="Round-robin autoplay across worlds until each reaches its attrition limit.")
    ap.add_argument("--config", required=True, help="worlds JSON (see docs)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--burst", type=int, default=25, help="fights per world before rotating")
    ap.add_argument("--interval", type=float, default=0.15, help="seconds between actions")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args(argv)

    try:
        worlds = load_world_plans(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"Bad config {args.config}: {exc}")
        return 1

    print(f"Farming {len(worlds)} world(s) on {args.cdp}:")
    for w in worlds:
        lim = "∞" if w.max_attrition >= UNLIMITED else w.max_attrition
        print(f"  {w.name}: fight ({w.x},{w.y}) + '{w.key}' until attrition {lim}")
    if not args.yes:
        try:
            if input("This will fight the live game automatically. Type 'yes': ").strip() != "yes":
                print("aborted."); return 1
        except EOFError:
            print("no confirmation (non-interactive) — pass --yes."); return 1
    try:
        status = run_round_robin_live(args.cdp, worlds, burst=args.burst, interval=args.interval)
        print("\n=== Summary ===")
        for w in worlds:
            st = status[w.name]
            mark = "DONE" if st.done else "stopped"
            print(f"  {w.name}: {mark} — {st.fights} fights, attrition {st.attrition}"
                  f"  ({st.reason or '-'})")
        return 0
    except KeyboardInterrupt:
        print("\nstopped by user."); return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Farm failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
