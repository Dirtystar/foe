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
from bap.forge.gbg_data.map_layout import MapTransform
from bap.forge.gbg_data.navigator import MapNavigator

_JS_NAMES = ("() => { const m = {}; document.querySelectorAll('tr[data-id]').forEach(tr => {"
             " const b = tr.querySelector('.prov-name b');"
             " if (b) m[tr.getAttribute('data-id')] = b.textContent.trim(); }); return m; }")


def _name(names, pid):
    return names.get(str(pid)) or f"#{pid}"


def _hover_click(page, x, y):  # pragma: no cover - live
    """Click (x, y) the way the FoE canvas needs it: a real mousemove trajectory to set the
    engine's hovered-target state, then press-hold-release. Plain CDP clicks do NOT register."""
    page.mouse.move(20, 20)
    page.wait_for_timeout(80)
    page.mouse.move(x, y, steps=25)
    page.wait_for_timeout(320)
    page.mouse.down()
    page.wait_for_timeout(80)
    page.mouse.up()


# A labeled CSS-pixel grid so we can read a canvas element's exact click coordinate.
_JS_GRID = """
() => {
  let o = document.getElementById('bapGrid'); if (o) o.remove();
  o = document.createElement('div'); o.id = 'bapGrid';
  o.style.cssText = 'position:fixed;inset:0;z-index:99998;pointer-events:none;';
  const W = window.innerWidth, H = window.innerHeight;
  const mk = (css, txt) => { const d = document.createElement('div'); d.style.cssText = css;
                             if (txt != null) d.textContent = txt; o.appendChild(d); };
  for (let gx = 0; gx < W; gx += 100) {
    mk('position:fixed;left:' + gx + 'px;top:0;width:1px;height:100%;background:rgba(255,40,40,.4)');
    mk('position:fixed;left:' + (gx+1) + 'px;top:1px;color:#ff0;background:rgba(0,0,0,.7);font:10px monospace;padding:0 1px', gx);
  }
  for (let gy = 0; gy < H; gy += 100) {
    mk('position:fixed;left:0;top:' + gy + 'px;width:100%;height:1px;background:rgba(255,40,40,.4)');
    mk('position:fixed;left:1px;top:' + (gy+1) + 'px;color:#ff0;background:rgba(0,0,0,.7);font:10px monospace;padding:0 1px', gy);
  }
  document.body.appendChild(o);
  return true;
}
"""

# Find the province window's action buttons (Útok/Vyjednávání) once it is open.
_JS_FIND_BUTTONS = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 18 || r.height < 10 || r.width > 400) continue;
    const txt = (el.textContent || '').replace(/\\s+/g,' ').trim();
    const cls = el.getAttribute('class') || '';
    if ((/^(útok|vyjednávání|budova|provincie)$/i.test(txt))
        || /attack|negotiat|province-window|btn-attack/i.test(cls)) {
      out.push({tag: el.tagName, cls: cls.slice(0,44), text: txt.slice(0,26),
                rect: [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)]});
    }
    if (out.length >= 30) break;
  }
  return out;
}
"""


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


# Report the topmost element at (x,y) and dispatch a full pointer+mouse sequence directly on
# the canvas — bypasses any overlay and any CDP-vs-DOM-listener gap.
_JS_PROBE_CLICK = """
([x, y]) => {
  const desc = e => e ? (e.tagName + '#' + (e.id||'') + '.'
                         + ((e.getAttribute && e.getAttribute('class')) || '')).slice(0,60) : 'null';
  const top = document.elementFromPoint(x, y);
  const canvas = document.querySelector('canvas');
  const target = canvas || top;
  const base = {bubbles:true, cancelable:true, clientX:x, clientY:y, screenX:x, screenY:y,
                view:window, button:0};
  for (const [type, buttons] of [['pointerdown',1],['mousedown',1],['pointerup',0],
                                 ['mouseup',0],['click',0]]) {
    const o = Object.assign({}, base, {buttons});
    try {
      const ev = type.startsWith('pointer')
        ? new PointerEvent(type, Object.assign({pointerId:1, pointerType:'mouse', isPrimary:true}, o))
        : new MouseEvent(type, o);
      target.dispatchEvent(ev);
    } catch (e) {}
  }
  return {topElement: desc(top), canvas: desc(canvas), dispatchedOn: desc(target)};
}
"""


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
             debug=False, overlay=False, attack=False, fight=False, utok=(1157, 800),
             autobattle=(1144, 800), connect=None):  # pragma: no cover - live
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
        if len(samples) >= 2:
            transform = solve_uniform(layout, samples)
        elif len(samples) == 1:
            # scale has been exactly 1.0 every run (map at 1:1 zoom); one marker fixes the offset
            s = samples[0]
            fx, fy = flags[s.province_id]
            transform = MapTransform(1.0, 1.0, s.screen[0] - fx, s.screen[1] - fy)
            print("Only 1 markable province — assuming scale=1.0 (observed every run); offset "
                  "from that one marker.", flush=True)
        else:
            print("No markable provinces found. Open the GBG map with the FoE Helper box "
                  "visible.", flush=True)
            return None
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

        if attack:
            from bap.forge.action.navigate import _pan as _pan_map
            ux, uy = utok
            # diagnosis: every attack-type, not-mine province the game currently reports
            bg = reader.snapshot
            if bg is not None:
                ref = bg.server_time or int(time.time())
                rows = [p for p in bg.provinces
                        if p.is_attack_battle_type and not bg.is_mine(p)]
                print(f"\n[attack] getBattleground has {len(rows)} attack-type foreign provinces:",
                      flush=True)
                for p in rows:
                    print(f"    {_name(names, p.id)} id={p.id} gain%={p.gain_attrition_chance} "
                          f"locked={p.is_locked(ref)} siege={bool(p.conquest_progress)}", flush=True)
            print(f"\n[attack] reaching the battle screen (Útok at ({ux},{uy})). Pans off-screen "
                  "targets in. Backs out with Escape — nothing is actually fought.", flush=True)
            reached = None
            for t in targets:
                f = flags.get(t.province_id)
                if f is None:
                    continue
                x, y = nav.screen_for(f)
                pans = 0
                while not (90 <= x <= vw - 90 and 90 <= y <= vh - 90) and pans < 4:
                    dx = max(-vw * 0.55, min(vw * 0.55, vw / 2 - x))
                    dy = max(-vh * 0.55, min(vh * 0.55, vh / 2 - y))
                    _pan_map(page, dx, dy, vw, vh)
                    nav.apply_drag(dx, dy)
                    pans += 1
                    x, y = nav.screen_for(f)
                if not (90 <= x <= vw - 90 and 90 <= y <= vh - 90):
                    print(f"  {_name(names, t.province_id)}: still off-screen after panning, "
                          "skipping", flush=True)
                    continue
                _hover_click(page, x, y)                    # open the province window
                page.wait_for_timeout(900)
                latest["pid"] = None
                latest["methods"] = []
                _hover_click(page, ux, uy)                  # Útok
                deadline = time.time() + 3.0
                while time.time() < deadline and latest["pid"] is None:
                    page.wait_for_timeout(150)
                if latest["pid"] is not None:
                    print(f"  ✅ {_name(names, t.province_id)} (id={t.province_id}): reached battle "
                          f"screen — getArmyPreview provinceId={latest['pid']}", flush=True)
                    reached = t.province_id
                    abx, aby = autobattle
                    page.evaluate(_JS_GRID)                 # grid to read the button coords off
                    page.evaluate(_JS_OVERLAY, [{"x": abx, "y": aby, "color": "#00e5ff",
                                                 "label": f"AutoBitva? ({abx},{aby})"}])
                    page.wait_for_timeout(150)
                    try:
                        page.screenshot(path="gbg_battle.png")
                    except Exception:
                        pass
                    print("  [armygrid] gbg_battle.png has the grid + cyan estimate — SEND it so I "
                          "can read the real Automatická bitva coordinate.", flush=True)
                    if fight:
                        before = reader.attrition_level
                        print(f"  [fight] clicking Automatická bitva at ({abx},{aby}) — REAL "
                              f"battle. attrition before={before}", flush=True)
                        _hover_click(page, abx, aby)
                        page.wait_for_timeout(4500)
                        try:
                            page.screenshot(path="gbg_fought.png")
                        except Exception:
                            pass
                        after = reader.attrition_level
                        print(f"  [fight] done. attrition {before} → {after}. SEND gbg_armygrid.png "
                              "(cyan dot vs the real Automatická bitva button — read the grid) and "
                              "gbg_fought.png.", flush=True)
                        _escape_to_map(page)
                    else:
                        _escape_to_map(page)                # back out, commit nothing
                    break
                print(f"  ⏭ {_name(names, t.province_id)} (id={t.province_id}): no army preview "
                      f"(guild-ignore dialog or locked) — methods={latest['methods'] or '(none)'}",
                      flush=True)
                _escape_to_map(page)                        # cancel dialog / close window
            if reached is not None:
                print(f"\n[attack] Full chain works end-to-end on province {reached}: map → open "
                      "→ Útok → battle screen. SEND gbg_battle.png. Ready for the fight loop! 🎯",
                      flush=True)
            else:
                print("\n[attack] No target reached the battle screen (all guild-ignored/locked "
                      "or off-screen). Re-run when normal attackable sectors are open.", flush=True)
            try:
                page.remove_listener("response", _on_response)
                page.remove_listener("request", _on_request)
            except Exception:
                pass
            return reached

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

            # click test: try several click STYLES on the most central on-screen target and
            # screenshot each, to find which actually opens the province window on the canvas.
            on = [(t, nav.screen_for(flags[t.province_id])) for t in targets
                  if t.province_id in flags]
            on = [(t, xy) for t, xy in on
                  if 80 <= xy[0] <= vw - 80 and 80 <= xy[1] <= vh - 80]
            if on:
                t, (x, y) = min(on, key=lambda p: (p[1][0] - vw / 2) ** 2 + (p[1][1] - vh / 2) ** 2)
                nm = _name(names, t.province_id)
                print(f"[overlay] opening {nm} at ({_r(x)},{_r(y)}) via hover-click…", flush=True)
                latest["pid"] = None
                latest["methods"] = []
                _hover_click(page, x, y)                    # opens the province window (works!)
                page.wait_for_timeout(1000)
                try:
                    page.screenshot(path="gbg_province.png")
                except Exception:
                    pass
                # find the Útok button in the now-open window
                import json as _json
                btns = page.evaluate(_JS_FIND_BUTTONS) or []
                print("[overlay] window buttons found in DOM:", flush=True)
                print(_json.dumps(btns, indent=2, ensure_ascii=False)[:2000] or "  (none — canvas)",
                      flush=True)
                attack_btn = next((b for b in btns if b["text"].strip().lower() == "útok"), None)
                if attack_btn:
                    ax = attack_btn["rect"][0] + attack_btn["rect"][2] // 2
                    ay = attack_btn["rect"][1] + attack_btn["rect"][3] // 2
                    print(f"[overlay] clicking Útok at ({ax},{ay})…", flush=True)
                    latest["pid"] = None
                    latest["methods"] = []
                    _hover_click(page, ax, ay)
                    page.wait_for_timeout(1600)
                    try:
                        page.screenshot(path="gbg_attack.png")
                    except Exception:
                        pass
                    print(f"    after Útok: provinceId={latest['pid']} "
                          f"methods={latest['methods'] or '(none)'}", flush=True)
                    print("[overlay] SEND gbg_province.png and gbg_attack.png (did the battle/army "
                          "screen open?).", flush=True)
                else:
                    ux, uy = utok
                    page.evaluate(_JS_GRID)                 # labeled CSS grid, in case we miss
                    page.evaluate(_JS_OVERLAY, [{"x": ux, "y": uy, "color": "#00e5ff",
                                                 "label": f"Útok? ({ux},{uy})"}])
                    page.wait_for_timeout(150)
                    try:
                        page.screenshot(path="gbg_grid.png")
                    except Exception:
                        pass
                    print(f"[overlay] Útok is canvas-drawn. Clicking estimate ({ux},{uy})…",
                          flush=True)
                    latest["pid"] = None
                    latest["methods"] = []
                    _hover_click(page, ux, uy)
                    page.wait_for_timeout(1600)
                    try:
                        page.screenshot(path="gbg_attack.png")
                    except Exception:
                        pass
                    print(f"    after Útok click: provinceId={latest['pid']} "
                          f"methods={latest['methods'] or '(none)'}", flush=True)
                    print("[overlay] SEND gbg_grid.png (cyan dot = where I clicked; if it's off "
                          "the Útok button, read the grid number under the real button) and "
                          "gbg_attack.png (did the army/battle screen open?).", flush=True)
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
            attack_els = [x for x in after if x.get("isAttack")]
            import json as _json
            print("[debug] newly-visible window/dialog candidates after click:", flush=True)
            print(_json.dumps(newvis, indent=2, ensure_ascii=False)[:3000] or "  (none)", flush=True)
            print("[debug] elements with Attack/Útok/Negotiate text (visible):", flush=True)
            print(_json.dumps(attack_els, indent=2, ensure_ascii=False)[:1500] or "  (none)", flush=True)
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
    ap.add_argument("--attack", action="store_true",
                    help="open each target and click Útok to reach the battle screen (backs out)")
    ap.add_argument("--fight", action="store_true",
                    help="with --attack: actually click Automatická bitva (fights ONE real battle)")
    ap.add_argument("--ux", type=int, default=1157, help="Útok button CSS x (canvas window)")
    ap.add_argument("--uy", type=int, default=800, help="Útok button CSS y (canvas window)")
    ap.add_argument("--abx", type=int, default=1144, help="Automatická bitva button CSS x")
    ap.add_argument("--aby", type=int, default=800, help="Automatická bitva button CSS y")
    args = ap.parse_args(argv)
    try:
        r = run_open(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index, n=args.n,
                     debug=args.debug, overlay=args.overlay, attack=args.attack or args.fight,
                     fight=args.fight, utok=(args.ux, args.uy), autobattle=(args.abx, args.aby))
        return 0 if r is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Open failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
