"""Map calibration CLI — click two provinces, the app learns the map→screen transform.

You never identify province ids: you open two provinces normally; the game reports each
``provinceId`` (in the `getArmyPreview` request) and we pair it with your click on that
province's flag. Two samples solve the transform, which is saved per (world, map) so it is
not repeated every start.

    bap-forge-calibrate --world cz6 --tab cz6

Read-only w.r.t. game state; it only watches traffic and your clicks. ``no-cover`` (needs a
live browser); the pairing/solve/persist logic underneath is unit-tested.
"""

from __future__ import annotations

import time

from bap.forge.gbg_data.calibration import (
    CalibrationCollector,
    load_calibration,
    save_calibration,
    solve_transform,
)


DEFAULT_STORE = "gbg_calibration.json"
_PROBE_JS = (
    "() => { if (window.__bapCal) return; window.__bapCal = 1;"
    " document.addEventListener('click',"
    " e => console.log('BAPCLICK ' + Math.round(e.clientX) + ' ' + Math.round(e.clientY)),"
    " true); }")


def run_calibrate(endpoint, world, *, tab=None, tab_index=None, store=DEFAULT_STORE,
                  connect=None, timeout_s=180.0):  # pragma: no cover - live
    from bap.forge.gbg_data.live import LiveGbgReader, make_response_handler
    from bap.forge.gbg_data.parser import parse_province_id_from_game_json
    from bap.forge.action.cdp_click import _select_page

    def _go(browser):
        page = _select_page(browser, index=tab_index, match=(tab or world))
        try:
            page.bring_to_front()
        except Exception:
            pass
        reader = LiveGbgReader()
        feed = make_response_handler(reader)
        collector = CalibrationCollector(need=2)

        def _on_response(resp):
            try:
                if "/game/json" in (resp.url or "") or "/map/data" in (resp.url or ""):
                    feed(resp)
            except BaseException:
                pass

        def _on_request(req):
            try:
                if "/game/json" not in (req.url or ""):
                    return
                import json as _j
                pid = parse_province_id_from_game_json(_j.loads(req.post_data or "[]"))
                if pid is not None:
                    collector.on_province(pid)
            except BaseException:
                pass

        def _on_console(msg):
            try:
                t = msg.text if hasattr(msg, "text") else str(msg)
                if t.startswith("BAPCLICK "):
                    _, x, y = t.split()
                    collector.on_click(int(x), int(y))
            except BaseException:
                pass

        page.on("response", _on_response)
        page.on("request", _on_request)
        page.on("console", _on_console)
        try:
            page.evaluate(_PROBE_JS)
        except Exception:
            pass

        print(f"Calibrating world {world} on {page.url}", flush=True)
        print("Open the GBG map so the layout loads…", flush=True)
        deadline = time.time() + 30
        while reader.map_layout is None and time.time() < deadline:
            page.wait_for_timeout(500)
        if reader.map_layout is None:
            print("No map layout seen — reload the GBG map, then re-run.", flush=True)
            return None
        map_id = reader.snapshot.map_id if reader.snapshot else None
        print(f"Map loaded ({len(reader.map_layout.flags)} provinces, id={map_id}).", flush=True)
        print("\nNow OPEN two different provinces (click the province, then Attack). "
              "Click the FIRST province's flag first.", flush=True)

        deadline = time.time() + timeout_s
        seen = 0
        while not collector.done and time.time() < deadline:
            page.wait_for_timeout(300)
            if len(collector.samples) != seen:
                seen = len(collector.samples)
                s = collector.samples[-1]
                print(f"  captured province {s.province_id} at screen {s.screen}"
                      f"  ({seen}/2) — now open a DIFFERENT province", flush=True)
        if not collector.done:
            print("Timed out before two provinces were captured.", flush=True)
            return None

        a, b = collector.samples[0], collector.samples[1]
        try:
            transform = solve_transform(reader.map_layout, a, b)
        except ValueError as exc:
            print(f"Could not solve: {exc}. Pick provinces further apart and retry.", flush=True)
            return None
        save_calibration(store, world, map_id, transform)
        print(f"\n✅ Calibrated {world} (map {map_id}) → saved to {store}", flush=True)
        print(f"   transform: scale=({transform.scale_x:.4f},{transform.scale_y:.4f}) "
              f"offset=({transform.off_x:.1f},{transform.off_y:.1f})", flush=True)
        try:
            page.remove_listener("response", _on_response)
            page.remove_listener("request", _on_request)
            page.remove_listener("console", _on_console)
        except Exception:
            pass
        return transform

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap = argparse.ArgumentParser(
        prog="bap-forge-calibrate",
        description="Learn the GBG map→screen transform by opening two provinces.")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz6)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    ap.add_argument("--store", default=DEFAULT_STORE, help="calibration file (JSON)")
    args = ap.parse_args(argv)
    try:
        t = run_calibrate(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index,
                          store=args.store)
        return 0 if t is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Calibration failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
