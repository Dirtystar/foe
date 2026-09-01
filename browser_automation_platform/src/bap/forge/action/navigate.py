"""Open a chosen province by clicking its computed flag point — and verify it.

With the calibrated map→screen transform, `province_screen_point(layout, transform, id)`
gives where a province's flag is on screen. Clicking it opens that province; the game then
sends a `getArmyPreview` request carrying the `provinceId`, so we can **verify** the click
opened the province we intended (observed id == requested id). This both proves the
calibration and is the core navigation primitive for B3.

    bap-forge-verify --world cz6            # click a few provinces by computed coords, check ids

Live glue is ``no-cover``; the geometry it relies on is unit-tested.
"""

from __future__ import annotations

import time

from bap.forge.gbg_data.calibration import load_calibration
from bap.forge.gbg_data.map_layout import province_screen_point

DEFAULT_STORE = "gbg_calibration.json"


def run_verify(endpoint, world, *, tab=None, tab_index=None, store=DEFAULT_STORE,
               n=3, connect=None):  # pragma: no cover - live
    from bap.forge.action.calibrate import _fetch_map_layout
    from bap.forge.action.cdp_click import CdpClicker, _select_page
    from bap.forge.gbg_data.live import LiveGbgReader, make_response_handler
    from bap.forge.gbg_data.parser import parse_province_id_from_game_json

    def _go(browser):
        page = _select_page(browser, index=tab_index, match=(tab or world))
        try:
            page.bring_to_front()
        except Exception:
            pass

        reader = LiveGbgReader()
        feed = make_response_handler(reader)
        latest = {"pid": None}

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
                    latest["pid"] = pid
            except BaseException:
                pass

        page.on("response", _on_response)
        page.on("request", _on_request)

        layout = _fetch_map_layout(page)
        deadline = time.time() + 15
        while layout is None and time.time() < deadline:
            page.wait_for_timeout(1000)
            layout = _fetch_map_layout(page)
        layout = layout or reader.map_layout
        if layout is None:
            print("Couldn't read the map layout — open the GBG map and re-run.", flush=True)
            return None

        map_id = reader.snapshot.map_id if reader.snapshot else None
        transform = load_calibration(store, world, map_id)
        if transform is None:
            print(f"No calibration for {world}/{map_id} in {store}. Run bap-forge-calibrate "
                  "first.", flush=True)
            return None

        # choose test provinces: prefer currently-attackable ones, else spread across the map
        pids = [t.province_id for t in reader.targets()][:n] if reader.snapshot else []
        if not pids:
            flags = sorted(layout.flags.items(), key=lambda kv: kv[1][0])
            pids = [flags[0][0], flags[len(flags) // 2][0], flags[-1][0]][:n]
        print(f"Verifying calibration by opening {len(pids)} provinces: {pids}", flush=True)

        clicker = CdpClicker(page)
        ok = 0
        for pid in pids:
            pt = province_screen_point(layout, transform, pid)
            if pt is None:
                continue
            latest["pid"] = None
            clicker.click_xy(*pt)
            got = None
            wait_until = time.time() + 4
            while time.time() < wait_until:
                page.wait_for_timeout(200)
                if latest["pid"] is not None:
                    got = latest["pid"]
                    break
            mark = "✅" if got == pid else "❌"
            print(f"  {mark} province {pid}: clicked ({pt[0]:.0f},{pt[1]:.0f}) → "
                  f"game opened {got}", flush=True)
            if got == pid:
                ok += 1
            page.wait_for_timeout(500)

        print(f"\n{ok}/{len(pids)} correct. "
              + ("Calibration is good — navigation works!" if ok == len(pids)
                 else "Some misses — re-calibrate with provinces further apart, or we add "
                      "more calibration points."), flush=True)
        try:
            page.remove_listener("response", _on_response)
            page.remove_listener("request", _on_request)
        except Exception:
            pass
        return ok

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap = argparse.ArgumentParser(
        prog="bap-forge-verify",
        description="Verify the map calibration by opening provinces at computed coords.")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz6)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    ap.add_argument("--store", default=DEFAULT_STORE, help="calibration file (JSON)")
    ap.add_argument("-n", type=int, default=3, help="how many provinces to test")
    args = ap.parse_args(argv)
    try:
        r = run_verify(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index,
                       store=args.store, n=args.n)
        return 0 if r is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Verify failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
