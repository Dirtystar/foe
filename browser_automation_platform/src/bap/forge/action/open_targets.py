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


# Visible "window / dialog / button" candidates — used to diff before/after a click, since
# FoE windows are pre-created DOM and merely shown/hidden (so they are not "new" nodes).
_JS_VISIBLE = """
() => {
  const kw = /window|dialog|province|battle|gbg|sector|attack|action|btn/i;
  const act = /\\bútok|attack|vyjedn|negoti/i;
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 14) continue;
    const cls = el.getAttribute('class') || '';
    const id = el.id || '';
    const txt = (el.textContent || '').replace(/\\s+/g,' ').trim();
    if (kw.test(cls + ' ' + id) || act.test(txt)) {
      out.push({id: id.slice(0,34), cls: cls.slice(0,44),
                text: txt.slice(0,44), isAttack: act.test(txt),
                rect: [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)]});
    }
    if (out.length >= 80) break;
  }
  return out;
}
"""


def _sig(x):
    return f"{x['id']}|{x['cls']}|{x['rect'][0] // 20}|{x['rect'][1] // 20}"


# Draw a dot + label at each predicted click point (CSS px == click coords == screenshot px),
# so a screenshot shows exactly where the tool would click.
_JS_OVERLAY = """
(pts) => {
  let o = document.getElementById('bapOverlay'); if (o) o.remove();
  o = document.createElement('div'); o.id = 'bapOverlay';
  for (const p of pts) {
    const d = document.createElement('div');
    d.style.cssText = 'position:fixed;z-index:99999;left:' + (p.x-9) + 'px;top:' + (p.y-9)
      + 'px;width:18px;height:18px;border-radius:50%;background:' + p.color
      + ';border:2px solid #fff;box-shadow:0 0 5px #000;pointer-events:none;';
    const l = document.createElement('div');
    l.textContent = p.label;
    l.style.cssText = 'position:fixed;z-index:99999;left:' + (p.x+11) + 'px;top:' + (p.y-10)
      + 'px;color:#fff;background:rgba(0,0,0,.7);padding:1px 4px;font:13px sans-serif;'
      + 'white-space:nowrap;pointer-events:none;';
    o.appendChild(d); o.appendChild(l);
  }
  document.body.appendChild(o);
  return true;
}
"""


def run_open(endpoint, world, *, tab=None, tab_index=None, n=5, store="gbg_calibration.json",
             debug=False, overlay=False, connect=None):  # pragma: no cover - live
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

        if overlay:
            pts = []
            for s in samples:                                 # green = known-correct markers
                x, y = s.screen
                pts.append({"x": x, "y": y, "color": "#22cc44",
                            "label": f"{_name(names, s.province_id)}(marker)"})
            for t in targets:                                 # red = predicted attackable targets
                f = flags.get(t.province_id)
                if f is None:
                    continue
                x, y = nav.screen_for(f)
                pts.append({"x": x, "y": y, "color": "#ee2222",
                            "label": f"{_name(names, t.province_id)} {t.gain_attrition_chance}%"})
            page.evaluate(_JS_OVERLAY, pts)
            page.wait_for_timeout(400)
            try:
                page.screenshot(path="gbg_overlay.png")
                print("\n[overlay] dots drawn → gbg_overlay.png (green=markers, red=targets).",
                      flush=True)
            except Exception as exc:
                print(f"[overlay] screenshot failed: {exc}", flush=True)

            # click test: click the first on-screen target, and a spot a bit BELOW it (into the
            # sector body, off the banner), screenshotting each so we see which opens the window.
            on = [(t, nav.screen_for(flags[t.province_id])) for t in targets
                  if t.province_id in flags]
            on = [(t, xy) for t, xy in on
                  if 80 <= xy[0] <= vw - 80 and 80 <= xy[1] <= vh - 80]
            if on:
                t, (x, y) = on[0]
                for dy, shot in ((0, "gbg_click_at.png"), (45, "gbg_click_below.png")):
                    latest["pid"] = None
                    latest["methods"] = []
                    clicker.click_xy(x, y + dy)
                    page.wait_for_timeout(1400)
                    try:
                        page.screenshot(path=shot)
                    except Exception:
                        pass
                    print(f"[overlay] clicked {_name(names, t.province_id)} at "
                          f"({_r(x)},{_r(y + dy)}) → provinceId={latest['pid']} "
                          f"methods={latest['methods'] or '(none)'} shot={shot}", flush=True)
            print("[overlay] SEND me gbg_overlay.png, gbg_click_at.png and gbg_click_below.png.",
                  flush=True)
            return 0

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
            before = {_sig(x) for x in (page.evaluate(_JS_VISIBLE) or [])}
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
            after = page.evaluate(_JS_VISIBLE) or []
            newvis = [x for x in after if _sig(x) not in before]
            attack = [x for x in after if x.get("isAttack")]
            import json as _json
            print("[debug] newly-visible window/dialog candidates after click:", flush=True)
            print(_json.dumps(newvis, indent=2, ensure_ascii=False)[:3000] or "  (none)", flush=True)
            print("[debug] elements with Attack/Útok/Negotiate text (visible):", flush=True)
            print(_json.dumps(attack, indent=2, ensure_ascii=False)[:1500] or "  (none)", flush=True)
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
    ap.add_argument("--overlay", action="store_true",
                    help="draw dots at predicted click points and screenshot (no clicking)")
    args = ap.parse_args(argv)
    try:
        r = run_open(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index, n=args.n,
                     debug=args.debug, overlay=args.overlay)
        return 0 if r is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Open failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
