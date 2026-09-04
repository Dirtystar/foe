"""Derive the GBG map→screen transform from FoE Helper's marker arrows — no human clicks.

Each marker arrow gives an exact (provinceId → screen) point; paired with that province's
map-space flag (from ``map/data``) it's a calibration sample. A handful solve the uniform
transform (``solve_uniform``), which then places *any* province — including the currently
attackable ones FoE Helper doesn't list (its "Next up" box is future unlocks). We mark every
province FoE Helper can mark (visible or not), read the arrows in one pass (no scrolling drift),
solve, and validate by leave-one-out prediction. The transform is saved per (world, map).

`bap-forge-solve --world cz2`. Live glue is ``no-cover``; the parser/solver are unit-tested.
"""

from __future__ import annotations

import time

from bap.forge.action.locate import clear_marker, locate_province
from bap.forge.gbg_data.calibration import (
    CalibrationSample,
    residual,
    save_calibration,
    solve_uniform,
)

_JS_MARKER_IDS = ("() => Array.from(document.querySelectorAll('button.building-marker-btn"
                  "[data-id]')).map(b => parseInt(b.getAttribute('data-id')))")

DEFAULT_STORE = "gbg_calibration.json"


def _leave_one_out(layout, samples):
    """Max prediction error (px) when each sample is predicted from a fit on the others."""
    if len(samples) < 3:
        return None
    worst = 0.0
    for i in range(len(samples)):
        rest = samples[:i] + samples[i + 1:]
        try:
            t = solve_uniform(layout, rest)
        except ValueError:
            continue
        fx, fy = layout.flag(samples[i].province_id)
        px, py = t.to_screen(fx, fy)
        sx, sy = samples[i].screen
        err = ((px - sx) ** 2 + (py - sy) ** 2) ** 0.5
        worst = max(worst, err)
    return worst


def run_solve(endpoint, world, *, tab=None, tab_index=None, store=DEFAULT_STORE,
              connect=None):  # pragma: no cover - live
    from bap.forge.action.calibrate import _fetch_map_layout
    from bap.forge.action.cdp_click import _select_page
    from bap.forge.gbg_data.live import LiveGbgReader, make_response_handler

    def _go(browser):
        page = _select_page(browser, index=tab_index, match=(tab or world))
        try:
            page.bring_to_front()
        except Exception:
            pass
        reader = LiveGbgReader()
        feed = make_response_handler(reader)

        def _on_response(resp):
            try:
                if "/game/json" in (resp.url or "") or "/map/data" in (resp.url or ""):
                    feed(resp)
            except BaseException:
                pass

        page.on("response", _on_response)

        layout = _fetch_map_layout(page)
        deadline = time.time() + 10
        while layout is None and time.time() < deadline:
            page.wait_for_timeout(1000)
            layout = _fetch_map_layout(page)
        layout = layout or reader.map_layout
        if layout is None:
            print("Couldn't read the map layout — open the GBG map and re-run.", flush=True)
            return None
        flags = layout.flags
        map_id = layout.map_id or (reader.snapshot.map_id if reader.snapshot else None)
        print(f"Map {map_id}: {len(flags)} provinces.", flush=True)

        ids = page.evaluate(_JS_MARKER_IDS) or []
        ids = list(dict.fromkeys(int(i) for i in ids if i in flags))
        if len(ids) < 2:
            print(f"Only {len(ids)} markable provinces found — need ≥2. Open the GBG map with "
                  "the FoE Helper box visible.", flush=True)
            return None
        print(f"Marking {len(ids)} provinces to read their screen points…", flush=True)

        samples = []
        for pid in ids:
            xy = locate_province(page, pid)
            clear_marker(page)
            if xy is not None:
                samples.append(CalibrationSample(pid, xy))
                print(f"  province {pid}: screen ({int(xy[0])},{int(xy[1])})", flush=True)
            else:
                print(f"  province {pid}: no arrow (skipped)", flush=True)
        if len(samples) < 2:
            print("Fewer than 2 usable marker points — cannot solve.", flush=True)
            return None

        try:
            transform = solve_uniform(layout, samples)
        except ValueError as exc:
            print(f"Solve failed: {exc}", flush=True)
            return None
        err = residual(layout, transform, samples)
        loo = _leave_one_out(layout, samples)
        save_calibration(store, world, map_id, transform)
        print(f"\n✅ Transform from {len(samples)} marker points → saved to {store}", flush=True)
        print(f"   scale={transform.scale_x:.4f}  offset=({transform.off_x:.1f},"
              f"{transform.off_y:.1f})", flush=True)
        print(f"   fit residual={err:.1f}px"
              + (f"   leave-one-out worst={loo:.1f}px" if loo is not None else ""), flush=True)
        good = err < 8 and (loo is None or loo < 15)
        print("   " + ("Rock solid — we can place any province now. 🎯" if good
                       else "High error — send the log; markers may span too small an area."),
              flush=True)
        try:
            page.remove_listener("response", _on_response)
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
        prog="bap-forge-solve",
        description="Derive & save the GBG map→screen transform from FoE Helper markers.")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz2)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    ap.add_argument("--store", default=DEFAULT_STORE, help="calibration file (JSON)")
    args = ap.parse_args(argv)
    try:
        t = run_solve(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index,
                      store=args.store)
        return 0 if t is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Solve failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
