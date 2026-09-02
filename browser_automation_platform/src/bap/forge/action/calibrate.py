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

import json

from bap.forge.gbg_data.calibration import (
    CalibrationCollector,
    load_calibration,
    residual,
    save_calibration,
    solve_uniform,
)
from bap.forge.gbg_data.map_layout import parse_map_data


def _fetch_map_layout(page, *, debug=False):  # pragma: no cover - live glue
    """Get the map/data asset even if it's served from cache: read its URL from the page's
    performance resource list, then fetch its body in the page context."""
    try:
        urls = page.evaluate(
            "() => performance.getEntriesByType('resource').map(e => e.name)"
            ".filter(n => n.includes('/map/data'))")
        if debug:
            print(f"  [debug] map/data URLs in performance: {urls}", flush=True)
        if not urls:
            return None
        body = page.evaluate("(u) => fetch(u).then(r => r.text()).catch(e => 'ERR:'+e)",
                             urls[0])
        if isinstance(body, str) and body.startswith("ERR:"):
            if debug:
                print(f"  [debug] fetch failed: {body[:120]}", flush=True)
            return None
        return parse_map_data(json.loads(body))
    except Exception as exc:
        if debug:
            print(f"  [debug] fetch/parse error: {exc}", flush=True)
        return None


DEFAULT_STORE = "gbg_calibration.json"
# Re-armable click probe: remove any previous handler and add a fresh one, so re-running it
# each loop re-attaches the listener if the game re-rendered the DOM and dropped it.
_PROBE_JS = (
    "() => { if (window.__bapClick) document.removeEventListener('click', window.__bapClick, true);"
    " window.__bapClick = e => console.log('BAPCLICK ' + Math.round(e.clientX) + ' '"
    " + Math.round(e.clientY));"
    " document.addEventListener('click', window.__bapClick, true); }")


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
        collector = CalibrationCollector(need=5)

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
                    print(f"  [debug] province event: {pid}  (last_click={collector._last_click})",
                          flush=True)
                    collector.on_province(pid)
            except BaseException as exc:
                print(f"  [debug] request parse error: {exc}", flush=True)

        def _on_console(msg):
            try:
                t = msg.text if hasattr(msg, "text") else str(msg)
                if t.startswith("BAPCLICK "):
                    _, x, y = t.split()
                    print(f"  [debug] click ({x},{y})", flush=True)
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
        print("Make sure you're on the GBG map…", flush=True)
        # 1) quick try: fetch the asset in-page (works if still in performance + CORS ok)
        layout = _fetch_map_layout(page, debug=True)
        if layout is None:
            # 2) robust: disable HTTP cache so the asset re-fetches over the wire (read via
            #    CDP, no CORS), then ask the user to reopen the GBG map.
            try:
                cdp = page.context.new_cdp_session(page)
                cdp.send("Network.enable")
                cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
            except Exception as exc:
                print(f"  [debug] could not disable cache: {exc}", flush=True)
            print("Now REOPEN the GBG map (go to your city and back into GBG) so it reloads…",
                  flush=True)
            deadline = time.time() + 90
            while layout is None and reader.map_layout is None and time.time() < deadline:
                page.wait_for_timeout(1000)
                layout = _fetch_map_layout(page)
            layout = layout or reader.map_layout
        if layout is None:
            print("Couldn't read the map layout. Tell Radek what the [debug] lines said.",
                  flush=True)
            return None
        map_id = reader.snapshot.map_id if reader.snapshot else None
        print(f"Map loaded ({len(layout.flags)} provinces, id={map_id}).", flush=True)
        try:
            vw = int(page.evaluate("() => window.innerWidth"))
            vh = int(page.evaluate("() => window.innerHeight"))
            print(f"Viewport: {vw}x{vh}.", flush=True)
            if vw > 2600 or vh > 1600:
                print("⚠ Viewport looks very large — your BROWSER is probably zoomed out "
                      "(Ctrl+scroll). Press Ctrl+0 to reset browser zoom to 100%, then zoom the "
                      "MAP with the in-game wheel/buttons only. Re-run after fixing.", flush=True)
        except Exception:
            pass
        need = collector.need
        print("\n>>> Browser zoom must be 100% (Ctrl+0). Use the DEFAULT GBG map view — don't "
              "browser-zoom. Then DON'T scroll/zoom the map again during or after this. <<<",
              flush=True)
        print(f"Now OPEN {need} DIFFERENT provinces, SPREAD across what you can see (corners + "
              "middle). For each: click the province, let its preview open, press Escape back "
              "to the map.", flush=True)

        deadline = time.time() + timeout_s
        seen = 0
        while not collector.done and time.time() < deadline:
            page.wait_for_timeout(300)
            try:
                page.evaluate(_PROBE_JS)     # re-arm in case the game dropped our listener
            except Exception:
                pass
            if len(collector.samples) != seen:
                seen = len(collector.samples)
                s = collector.samples[-1]
                print(f"  captured province {s.province_id} at screen {s.screen}"
                      f"  ({seen}/{need}) — open a DIFFERENT province", flush=True)
        if not collector.done:
            print(f"Timed out with {len(collector.samples)}/{need} provinces.", flush=True)
            return None

        try:
            transform = solve_uniform(layout, collector.samples)   # uniform-scale least squares
        except ValueError as exc:
            print(f"Could not solve: {exc}. Open provinces spread further apart and retry.",
                  flush=True)
            return None
        err = residual(layout, transform, collector.samples)
        save_calibration(store, world, map_id, transform)
        print(f"\n✅ Calibrated {world} (map {map_id}) from {len(collector.samples)} provinces "
              f"→ saved to {store}", flush=True)
        print(f"   scale={transform.scale_x:.4f}  offset=({transform.off_x:.1f},"
              f"{transform.off_y:.1f})  worst fit error={err:.0f}px", flush=True)
        if err > 40:
            print("   ⚠ fit error is high — clicks may have been imprecise or provinces too "
                  "clustered. Consider re-running and clicking flag centres, well spread.",
                  flush=True)
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
