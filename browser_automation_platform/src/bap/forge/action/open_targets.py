"""End-to-end B3: place attackable provinces on screen via the marker-solved transform.

One pass:
  1. read the map flags and FoE Helper's id→name map,
  2. solve the map→screen transform from marker arrows (no human clicks),
  3. take the **native** attackable targets from getBattleground (the real fight list —
     FoE Helper's "Next up" box is future unlocks, not this),
  4. open each target: transform → pan on-screen → click → confirm the reported provinceId,
     self-correcting the offset from every province actually hit.

`bap-forge-open --world cz2` proves navigation on real fight targets before the fight loop is
built on it. Live glue is ``no-cover``; the transform/parse pieces are unit-tested.
"""

from __future__ import annotations

import time

from bap.forge.action.locate import clear_marker, locate_province
from bap.forge.action.navigate import _escape_to_map, _r, _viewport, open_province
from bap.forge.action.solve import _JS_MARKER_IDS
from bap.forge.gbg_data.calibration import CalibrationSample, residual, save_calibration, solve_uniform
from bap.forge.gbg_data.navigator import MapNavigator

_JS_NAMES = ("() => { const m = {}; document.querySelectorAll('tr[data-id]').forEach(tr => {"
             " const b = tr.querySelector('.prov-name b');"
             " if (b) m[tr.getAttribute('data-id')] = b.textContent.trim(); }); return m; }")


def _name(names, pid):
    return names.get(str(pid)) or f"#{pid}"


_JS_TAG = "() => { document.querySelectorAll('body *').forEach(e => e.setAttribute('data-bapseen','1')); return true; }"
_JS_NEW_WINDOW = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('body *:not([data-bapseen])')) {
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 30) continue;
    out.push({tag: el.tagName, id: (el.id||'').slice(0,40),
              cls: (el.getAttribute('class')||'').slice(0,50),
              text: (el.textContent||'').replace(/\\s+/g,' ').trim().slice(0,70),
              rect: [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)]});
    if (out.length >= 20) break;
  }
  return out;
}
"""


def run_open(endpoint, world, *, tab=None, tab_index=None, n=5, store="gbg_calibration.json",
             debug=False, connect=None):  # pragma: no cover - live
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
        latest = {"pid": None, "methods": []}

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
                batch = _j.loads(req.post_data or "[]")
                for r in batch if isinstance(batch, list) else []:
                    if isinstance(r, dict):
                        latest["methods"].append(
                            f"{r.get('requestClass')}.{r.get('requestMethod')}")
                pid = parse_province_id_from_game_json(batch)
                if pid is not None:
                    latest["pid"] = pid
            except BaseException:
                pass

        page.on("response", _on_response)
        page.on("request", _on_request)

        # --- flags + names -----------------------------------------------------
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
        names = page.evaluate(_JS_NAMES) or {}
        vw, vh = _viewport(page)
        print(f"Map {layout.map_id}: {len(flags)} provinces. Viewport {vw}x{vh}.", flush=True)

        # --- solve transform from marker arrows --------------------------------
        ids = [int(i) for i in (page.evaluate(_JS_MARKER_IDS) or []) if int(i) in flags]
        ids = list(dict.fromkeys(ids))
        samples = []
        for pid in ids:
            xy = locate_province(page, pid)
            clear_marker(page)
            if xy is not None:
                samples.append(CalibrationSample(pid, xy))
                print(f"  marker {_name(names, pid)} (id={pid}): screen ({_r(xy[0])},{_r(xy[1])})",
                      flush=True)
        if len(samples) < 2:
            print("Need ≥2 marker points to solve the transform. Open the GBG map with the FoE "
                  "Helper box visible.", flush=True)
            return None
        transform = solve_uniform(layout, samples)
        save_calibration(store, world, layout.map_id, transform)
        print(f"Transform: scale={transform.scale_x:.4f} offset=({transform.off_x:.0f},"
              f"{transform.off_y:.0f})  residual={residual(layout, transform, samples):.1f}px",
              flush=True)
        nav = MapNavigator(scale=transform.scale_x, off_x=transform.off_x, off_y=transform.off_y)

        # --- native attackable targets ----------------------------------------
        deadline = time.time() + 12
        while reader.snapshot is None and time.time() < deadline:
            page.wait_for_timeout(1000)
        targets = reader.targets(include_locked=False) if reader.snapshot else []
        if not targets:
            print("\nNo attackable provinces right now (getBattleground reports none open). The "
                  "transform is solved & saved — re-run when sectors are open to fight.", flush=True)
            return 0
        targets = targets[:n]
        print(f"\nAttackable now ({len(targets)}): "
              + ", ".join(f"{_name(names, t.province_id)}[{t.gain_attrition_chance}%]"
                          for t in targets), flush=True)
        _escape_to_map(page)
        clicker = CdpClicker(page)

        if debug:
            # is the transform still valid right now? re-read a marker and compare to prediction.
            chk = samples[0].province_id
            axy = locate_province(page, chk)
            clear_marker(page)
            if axy is not None:
                px, py = nav.screen_for(flags[chk])
                print(f"\n[debug] transform check id={chk}: predicted ({_r(px)},{_r(py)}) vs "
                      f"actual ({_r(axy[0])},{_r(axy[1])}) delta=({_r(axy[0]-px)},{_r(axy[1]-py)})",
                      flush=True)
            print("\n[debug] predicted screen positions:", flush=True)
            on_screen = []
            for t in targets:
                f = flags.get(t.province_id)
                if f is None:
                    continue
                sx, sy = nav.screen_for(f)
                ok_pos = 80 <= sx <= vw - 80 and 80 <= sy <= vh - 80
                print(f"  {_name(names, t.province_id)} id={t.province_id}: flag=({_r(f[0])},"
                      f"{_r(f[1])}) → screen ({_r(sx)},{_r(sy)}) {'ON' if ok_pos else 'OFF'}-screen",
                      flush=True)
                if ok_pos:
                    on_screen.append((t, (sx, sy)))
            if not on_screen:
                print("[debug] none predicted on-screen — pan logic needed; stop here.", flush=True)
                return 0
            t, scr = on_screen[0]
            print(f"\n[debug] clicking {_name(names, t.province_id)} at ({_r(scr[0])},{_r(scr[1])}) "
                  "and watching what happens…", flush=True)
            page.evaluate(_JS_TAG)
            latest["pid"] = None
            latest["methods"] = []
            clicker.click_xy(scr[0], scr[1])
            page.wait_for_timeout(1800)
            shot = "gbg_debug_after_click.png"
            try:
                page.screenshot(path=shot)
                print(f"[debug] screenshot saved → {shot} (SEND me this image)", flush=True)
            except Exception as exc:
                print(f"[debug] screenshot failed: {exc}", flush=True)
            print(f"[debug] provinceId seen: {latest['pid']}", flush=True)
            print(f"[debug] /game/json methods fired: {latest['methods'] or '(none)'}", flush=True)
            import json as _json
            wins = page.evaluate(_JS_NEW_WINDOW)
            print("[debug] new DOM windows/panels after click:", flush=True)
            print(_json.dumps(wins, indent=2, ensure_ascii=False)[:3500], flush=True)
            return 0

        print("Opening each via the transform (pan + click + confirm)…", flush=True)
        ok = 0
        for t in targets:
            pid = t.province_id
            scr = open_province(page, clicker, nav, latest, flags, pid, vw, vh)
            mark = "✅" if scr else "❌"
            where = f"opened at ({_r(scr[0])},{_r(scr[1])})" if scr else "could not confirm"
            print(f"  {mark} {_name(names, pid)} (id={pid}, {t.gain_attrition_chance}%): {where}",
                  flush=True)
            if scr:
                ok += 1
        print(f"\n{ok}/{len(targets)} attackable provinces opened correctly. "
              + ("B3 solved end-to-end — ready for the fight loop! 🎯" if ok == len(targets)
                 else "Some misses — send the log."), flush=True)
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
        prog="bap-forge-open",
        description="Open attackable GBG provinces via the marker-solved transform.")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz2)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    ap.add_argument("-n", type=int, default=5, help="how many attackable provinces to open")
    ap.add_argument("--debug", action="store_true",
                    help="click the first on-screen target and dump requests + new DOM windows")
    args = ap.parse_args(argv)
    try:
        r = run_open(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index, n=args.n,
                     debug=args.debug)
        return 0 if r is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Open failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
