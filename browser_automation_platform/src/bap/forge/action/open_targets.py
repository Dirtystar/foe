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

import json
import os
import re
import time

_SKIP_FILE = "gbg_skip.json"


def _skip_load(round_key):
    """Load the never-fightable provinceIds learned for THIS round (keyed by world+endsAt, so
    it resets automatically when a new round with a different map starts)."""
    try:
        return set(json.load(open(_SKIP_FILE, encoding="utf-8")).get(round_key, []))
    except Exception:
        return set()


def _skip_save(round_key, s):
    try:
        d = json.load(open(_SKIP_FILE, encoding="utf-8")) if os.path.exists(_SKIP_FILE) else {}
    except Exception:
        d = {}
    d[round_key] = sorted(s)
    try:
        json.dump(d, open(_SKIP_FILE, "w", encoding="utf-8"))
    except Exception:
        pass

from bap.forge.action.locate import clear_marker, locate_province
from bap.forge.action.navigate import _escape_to_map, _r, _viewport, open_province
from bap.forge.action.solve import _JS_MARKER_IDS
from bap.forge.gbg_data.calibration import CalibrationSample, residual, save_calibration, solve_uniform
from bap.forge.gbg_data.map_layout import MapTransform
from bap.forge.gbg_data.navigator import MapNavigator

_JS_NAMES = ("() => { const m = {}; document.querySelectorAll('tr[data-id]').forEach(tr => {"
             " const b = tr.querySelector('.prov-name b');"
             " if (b) m[tr.getAttribute('data-id')] = b.textContent.trim(); }); return m; }")


# Leader "Cíl" (focus target) marks from FoE Helper — those rows carry a .focus-target img.
_JS_CIL = ("() => Array.from(document.querySelectorAll('tr[data-id]'))"
           ".filter(tr => tr.querySelector('.focus-target'))"
           ".map(tr => parseInt(tr.getAttribute('data-id')))")


def _name(names, pid):
    return names.get(str(pid)) or f"#{pid}"


def _ring(name):
    """Ring number from a province name (A1→1, B4→4, X1→1); unknown → 9 (fight last)."""
    m = re.search(r"\d", name or "")
    return int(m.group()) if m else 9


# FoE modal windows centre on the viewport, so their canvas buttons sit at a fixed OFFSET from
# the viewport centre (measured at 2304x1042: Útok (1157,800), Automatická bitva (1150,790)).
# Deriving from the live centre makes them work at any browser window size.
_UTOK_OFF = (5, 279)
_AUTOBATTLE_OFF = (-2, 269)


def _centre_button(vw, vh, off):
    return (round(vw / 2) + off[0], round(vh / 2) + off[1])


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


def _refresh_offset(page, nav, flags, marker_ids):  # pragma: no cover - live
    """Reset the offset to the map's CURRENT position by re-reading a marker arrow (scale is
    fixed), so positioning stays exact after panning. Returns True on success."""
    if not _in_gbg(page):                                  # never mark/click off the GBG map
        return False
    for mid in marker_ids:
        fl = flags.get(mid)
        if fl is None:
            continue
        axy = locate_province(page, mid)
        clear_marker(page)
        if axy is not None:
            nav.off_x = axy[0] - nav.scale * fl[0]
            nav.off_y = axy[1] - nav.scale * fl[1]
            return True
    return False


def _in_gbg(page):  # pragma: no cover - live
    # TODO: FoE-Helper-dependent signal — replace with a native check when we drop that crutch.
    try:
        return bool(page.evaluate("() => !!document.querySelector('.gbg-tabs')"))
    except Exception:
        return False


def _enter_gbg(page, reader, gbg_pos, *, tries=4, per_wait=15):  # pragma: no cover - live
    """Self-healing: guarantee we're on the GBG map with a fresh getBattleground. getBattleground
    only fires on GBG entry, so if we're already in GBG with no captured snapshot we reload to
    the city first, then click the entrance. Retries; returns the fresh snapshot or None."""
    for attempt in range(1, tries + 1):
        if reader.snapshot is not None:
            page.wait_for_timeout(800)
            return reader.snapshot
        if _in_gbg(page):
            print(f"[enter] in GBG but no fresh data — reloading to the city to re-enter "
                  f"(try {attempt})…", flush=True)
            try:
                page.reload()
            except Exception:
                pass
            page.wait_for_timeout(3500)
        _hover_click(page, gbg_pos[0], gbg_pos[1])          # click the city GBG entrance
        print(f"[enter] clicked GBG entrance ({gbg_pos[0]},{gbg_pos[1]}); waiting for "
              f"getBattleground (try {attempt}/{tries})…", flush=True)
        deadline = time.time() + per_wait
        while reader.snapshot is None and time.time() < deadline:
            page.wait_for_timeout(1000)
    return reader.snapshot


def _run_fight_loop(page, clicker, reader, latest, autobattle, *, repeat, limit,
                    inter_ms, reload_every, stall_stop=12):  # pragma: no cover - live
    """Fight the province currently on the army screen: click Automatická bitva each iteration,
    press R (Reload units) every ``reload_every`` fights, stop at the attrition ``limit`` or
    after ``stall_stop`` consecutive non-starting clicks (province conquered / screen changed).
    Returns "limit" if the attrition limit was reached, else "done"."""
    abx, aby = autobattle
    # Set hover once (the canvas needs a real mousemove), then rapid down/up at the same point —
    # like the manual F10 cadence (click + R every N), instead of a full trajectory per fight.
    try:
        page.mouse.move(20, 20)
        page.wait_for_timeout(60)
        page.mouse.move(abx, aby, steps=15)
        page.wait_for_timeout(150)
    except Exception:
        pass
    latest["methods"] = []
    misses = 0
    started_total = 0
    for i in range(repeat):
        if i % 8 == 0:                                     # periodic safety checks (kept cheap)
            if not _in_gbg(page):
                print("  left the GBG map — stopping fight loop.", flush=True)
                return "left"
            lvl = reader.attrition_level
            if limit is not None and lvl is not None and lvl >= limit:
                print(f"  attrition {lvl} ≥ limit {limit} — STOP.", flush=True)
                return "limit"
        seen = len(latest["methods"])
        try:
            page.mouse.down()                              # click at the hovered auto-battle button
            page.mouse.up()
        except Exception:
            pass
        if reload_every and (i + 1) % reload_every == 0:
            try:
                clicker.press("r")                         # replenish attacking units
            except Exception:
                pass
        page.wait_for_timeout(inter_ms)
        if any("startByBattleType" in m for m in latest["methods"][seen:]):
            started_total += 1
            misses = 0
        else:
            misses += 1
        if misses >= stall_stop:
            print(f"  {misses} clicks without a battle — province done / screen changed "
                  f"(~{started_total} fought, attrition {reader.attrition_level}).", flush=True)
            break
    else:
        print(f"  ~{started_total} fought, attrition {reader.attrition_level}.", flush=True)
    return "done"


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
             debug=False, overlay=False, attack=False, fight=False, grid_only=False,
             click_here=False, repeat=1, limit=None, inter_ms=150, reload_every=5,
             watch=0, reload_first=False, enter_gbg=False, gbg_pos=(1650, 250),
             farm=False, pcts=None, skip=None, find_gbg=False, utok=None, autobattle=None,
             connect=None):  # pragma: no cover - live
    skip = skip if skip is not None else set()             # provinceIds that never reach a fight
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

        if grid_only:
            # Just label the current screen — for reading a canvas button's coordinate.
            # Manually open the province → Útok → Správa armády first, then run this.
            page.evaluate(_JS_GRID)
            page.wait_for_timeout(250)
            try:
                page.screenshot(path="gbg_screen_grid.png")
            except Exception:
                pass
            print("Drew a labeled CSS grid on the current screen → gbg_screen_grid.png. SEND it "
                  "(I'll read the Automatická bitva coordinate off the yellow grid numbers).",
                  flush=True)
            return 0
        reader = LiveGbgReader()
        latest = {"pid": None, "methods": []}

        def _on_upd(r):
            if not watch:
                return
            bg = r.snapshot
            if bg is None:
                return
            ref = bg.server_time or int(time.time())
            openatk = [p for p in bg.provinces if p.is_attack_battle_type and not bg.is_mine(p)
                       and not p.is_locked(ref) and p.gain_attrition_chance is not None]
            pcts = sorted({p.gain_attrition_chance for p in bg.provinces
                           if p.gain_attrition_chance is not None})
            print(f"[watch] {time.strftime('%H:%M:%S')} getBattleground refresh → "
                  f"{len(openatk)} open-attackable, %s present={pcts}", flush=True)

        feed = make_response_handler(reader, on_update=_on_upd)

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
                methods = []
                for r in batch if isinstance(batch, list) else []:
                    if isinstance(r, dict):
                        methods.append(f"{r.get('requestClass')}.{r.get('requestMethod')}")
                latest["methods"].extend(methods)
                if watch and methods:
                    print(f"[watch] {time.strftime('%H:%M:%S')} request: {', '.join(methods)}",
                          flush=True)
                pid = parse_province_id_from_game_json(batch)
                if pid is not None:
                    latest["pid"] = pid
            except BaseException:
                pass

        page.on("response", _on_response)
        page.on("request", _on_request)

        # FoE windows centre on the viewport → derive button coords from the live centre so they
        # work at any browser window size (unless the caller pinned them explicitly).
        _vw0, _vh0 = _viewport(page)
        utok_xy = utok or _centre_button(_vw0, _vh0, _UTOK_OFF)
        autobattle_xy = autobattle or _centre_button(_vw0, _vh0, _AUTOBATTLE_OFF)
        print(f"[calib] viewport {_vw0}x{_vh0} → Útok {utok_xy}, Auto-battle {autobattle_xy}",
              flush=True)

        if find_gbg:
            # In the CITY: hunt for a DOM element that opens GBG (viewport-independent entry).
            js = ("() => Array.from(document.querySelectorAll('*')).map(el => {"
                  " const s=((el.id||'')+' '+((el.getAttribute&&el.getAttribute('class'))||'')+' '"
                  " +(el.getAttribute&&(el.getAttribute('title')||el.getAttribute('data-original-title'))||'')"
                  " +' '+((el.textContent||'').slice(0,30))).toLowerCase();"
                  " if(!/gbg|battleground|bitevní|bojiště|guildbattle/.test(s)) return null;"
                  " const r=el.getBoundingClientRect();"
                  " return {tag:el.tagName,id:(el.id||'').slice(0,30),"
                  " cls:((el.getAttribute&&el.getAttribute('class'))||'').slice(0,50),"
                  " title:((el.getAttribute&&(el.getAttribute('title')||el.getAttribute('data-original-title')))||'').slice(0,40),"
                  " rect:[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)]};"
                  " }).filter(x=>x && x.rect[2]>0)")
            hits = page.evaluate(js) or []
            import json as _j
            print(f"[find-gbg] {len(hits)} DOM elements mention GBG (in the city):", flush=True)
            print(_j.dumps(hits, indent=2, ensure_ascii=False)[:3000], flush=True)
            print("[find-gbg] if any is a clickable icon/button for GBG, we click it by selector "
                  "→ resolution-independent entry.", flush=True)
            return 0

        if enter_gbg or farm:
            gx, gy = gbg_pos
            print(f"[enter] opening GBG via the city entrance ({gx},{gy}) for fresh data…",
                  flush=True)
            bg = _enter_gbg(page, reader, gbg_pos)
            if bg is None:
                try:
                    page.screenshot(path="gbg_entered.png")
                except Exception:
                    pass
                print("[enter] no getBattleground — the entrance coord may be off (--gbg-x/-y). "
                      "SEND gbg_entered.png.", flush=True)
                return 0
            ref = bg.server_time or int(time.time())
            names0 = page.evaluate(_JS_NAMES) or {}
            openatk = [p for p in bg.provinces if p.is_attack_battle_type and not bg.is_mine(p)
                       and not p.is_locked(ref) and p.gain_attrition_chance is not None]
            print(f"[enter] entered GBG, fresh data: {len(openatk)} open-attackable "
                  + ", ".join(f"{_name(names0, p.id)}[{p.gain_attrition_chance}%]"
                              for p in sorted(openatk,
                                              key=lambda p: (p.gain_attrition_chance, p.id))),
                  flush=True)
            if not farm:
                try:
                    page.screenshot(path="gbg_entered.png")
                except Exception:
                    pass
                return 0
            # farm: fall through to solve transform + select + fight loop

        if reload_first:
            print("[reload] reloading the tab to force a fresh getBattleground (login prefetches "
                  "it)…", flush=True)
            try:
                page.reload()
            except Exception as exc:
                print(f"[reload] reload error: {exc}", flush=True)
            deadline = time.time() + 40
            while reader.snapshot is None and time.time() < deadline:
                page.wait_for_timeout(1000)
            bg = reader.snapshot
            if bg is None:
                print("[reload] no getBattleground within 40s after reload.", flush=True)
                try:
                    page.screenshot(path="gbg_afterreload.png")
                except Exception:
                    pass
                return 0
            ref = bg.server_time or int(time.time())
            names = page.evaluate(_JS_NAMES) or {}
            openatk = [p for p in bg.provinces if p.is_attack_battle_type and not bg.is_mine(p)
                       and not p.is_locked(ref) and p.gain_attrition_chance is not None]
            print(f"[reload] fresh getBattleground: {len(openatk)} open-attackable:", flush=True)
            for p in sorted(openatk, key=lambda p: (p.gain_attrition_chance, p.id)):
                print(f"    {_name(names, p.id)} id={p.id} gain%={p.gain_attrition_chance}",
                      flush=True)
            try:
                page.screenshot(path="gbg_afterreload.png")
            except Exception:
                pass
            print("[reload] SEND gbg_afterreload.png — is the game on the GBG map or in the city "
                  "after reload?", flush=True)
            return 0

        if watch:
            names = page.evaluate(_JS_NAMES) or {}
            print(f"[watch] listening {watch}s for getBattleground refreshes. Try interacting "
                  "with the map / reopening GBG to see if the data updates.", flush=True)
            deadline = time.time() + watch
            while time.time() < deadline:
                page.wait_for_timeout(1000)
            bg = reader.snapshot
            if bg is None:
                print("[watch] never saw a getBattleground — reopen the GBG map.", flush=True)
                return 0
            ref = bg.server_time or int(time.time())
            withpct = [p for p in bg.provinces if p.gain_attrition_chance is not None]
            print(f"\n[watch] latest snapshot: {len(bg.provinces)} provinces, "
                  f"{len(withpct)} with a %:", flush=True)
            for p in sorted(withpct, key=lambda p: p.id):
                print(f"  {_name(names, p.id)} id={p.id} atk={p.is_attack_battle_type} "
                      f"mine={bg.is_mine(p)} gain%={p.gain_attrition_chance} "
                      f"locked={p.is_locked(ref)}", flush=True)
            sixty = [p for p in bg.provinces if p.gain_attrition_chance == 60]
            print(f"[watch] 60% provinces in data: {[p.id for p in sixty] or 'NONE'}", flush=True)
            return 0

        if click_here:
            # Fight the current province over and over. Each iteration clicks Automatická bitva
            # (the actual battle); every `reload_every` fights we press 'r' (Reload) to replenish
            # the attacking units so the army stays strong. Stops at the attrition limit.
            clicker = CdpClicker(page)
            print(f"[click] fighting × {repeat} (auto-battle each; R-reload every {reload_every}), "
                  f"limit={limit}, {inter_ms}ms apart. Be on the attack army screen.", flush=True)
            fought = _run_fight_loop(page, clicker, reader, latest, autobattle_xy, repeat=repeat,
                                     limit=limit, inter_ms=inter_ms, reload_every=reload_every)
            print(f"[click] {fought}/{repeat} battles started. Attrition now "
                  f"{reader.attrition_level}.", flush=True)
            return 0

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
        targets = (reader.targets(include_locked=False, allowed_pcts=pcts)
                   if reader.snapshot else [])
        if not targets:
            print(f"\nNo attackable provinces right now (allowed %={pcts or 'all'}). Transform "
                  "saved — re-run when sectors are open.", flush=True)
            return 0
        # skip-list is keyed by the ROUND (world + endsAt) so it resets when the map changes
        round_key = f"{world}::{reader.snapshot.ends_at if reader.snapshot else '?'}"
        skip.update(_skip_load(round_key))                 # mutate in place (no rebind in closure)
        targets = [t for t in targets if t.province_id not in skip]  # learned non-fightable
        # Cíl (leader focus target) overrides the % allowlist and gets absolute priority
        try:
            cil = {int(i) for i in (page.evaluate(_JS_CIL) or [])}
        except Exception:
            cil = set()
        if cil:
            have = {t.province_id for t in targets}
            for t in reader.targets(include_locked=False):       # all %, add Cíl even if % not allowed
                if t.province_id in cil and t.province_id not in skip and t.province_id not in have:
                    targets.append(t)
            print(f"[cíl] leader targets prioritised: {sorted(cil)}", flush=True)
        # order: Cíl first, then lowest % (20→40→60), then centre rings (…1 before …4)
        targets.sort(key=lambda t: (
            0 if t.province_id in cil else 1,
            t.gain_attrition_chance if t.gain_attrition_chance is not None else 999,
            _ring(names.get(str(t.province_id), "")),
            t.province_id))
        targets = targets[:(n if not farm else len(targets))]
        print(f"\nAttackable now ({len(targets)}, allowed %={pcts or 'all'}, skip={sorted(skip)}): "
              + ", ".join(f"{_name(names, t.province_id)}[{t.gain_attrition_chance}%]"
                          for t in targets), flush=True)
        _escape_to_map(page)
        clicker = CdpClicker(page)

        if attack:
            from bap.forge.action.navigate import _pan as _pan_map
            ux, uy = utok_xy
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
            if farm:
                print(f"\n[farm] farming {world} to attrition limit={limit}, allowed %={pcts or 'all'}.",
                      flush=True)
            else:
                print(f"\n[attack] reaching the battle screen (Útok at ({ux},{uy})). Pans off-screen "
                      "targets in. Backs out with Escape — nothing is actually fought.", flush=True)
            reached = None
            marker_ids = [s.province_id for s in samples]   # markable provinces = offset anchors
            for t in targets:
                if farm and not _in_gbg(page):
                    print("[farm] no longer on the GBG map — stopping this pass.", flush=True)
                    break
                lvl = reader.attrition_level
                if limit is not None and lvl is not None and lvl >= limit:
                    print(f"[farm] attrition {lvl} ≥ limit {limit} — world done.", flush=True)
                    break
                f = flags.get(t.province_id)
                if f is None:
                    continue
                # bring the target on-screen, re-reading a marker arrow after each drag so the
                # offset stays exact (blind panning drifts on far/opposite-side provinces).
                x, y = nav.screen_for(f)
                for _ in range(6):
                    if not _refresh_offset(page, nav, flags, marker_ids):
                        break                               # off the GBG map — don't pan blindly
                    x, y = nav.screen_for(f)
                    if 90 <= x <= vw - 90 and 90 <= y <= vh - 90:
                        break
                    dx = max(-vw * 0.5, min(vw * 0.5, vw / 2 - x))
                    dy = max(-vh * 0.5, min(vh * 0.5, vh / 2 - y))
                    _pan_map(page, dx, dy, vw, vh)
                if not (90 <= x <= vw - 90 and 90 <= y <= vh - 90):
                    print(f"  {_name(names, t.province_id)}: couldn't bring on-screen, skipping",
                          flush=True)
                    continue
                # try the flag, then into the sector body, then above — banners sit at the
                # sector's top edge, so a small nudge often lands the click on the real sector.
                for dy in (0, 40, -30, 75):
                    _hover_click(page, x, y + dy)           # open the province window
                    page.wait_for_timeout(900)
                    latest["pid"] = None
                    latest["methods"] = []
                    _hover_click(page, ux, uy)              # Útok
                    deadline = time.time() + 2.5
                    while time.time() < deadline and latest["pid"] is None:
                        page.wait_for_timeout(150)
                    if latest["pid"] is not None:
                        break
                    _escape_to_map(page)                    # close wrong/empty window, retry
                if latest["pid"] is not None:
                    print(f"  ✅ {_name(names, t.province_id)} (id={t.province_id}): reached battle "
                          f"screen — getArmyPreview provinceId={latest['pid']}", flush=True)
                    reached = t.province_id
                    if fight:
                        print(f"  [fight] farming {_name(names, t.province_id)} to attrition "
                              f"limit={limit}…", flush=True)
                        status = _run_fight_loop(page, clicker, reader, latest, autobattle_xy,
                                                 repeat=repeat, limit=limit, inter_ms=inter_ms,
                                                 reload_every=reload_every)
                        _escape_to_map(page)
                        if farm:
                            if status in ("limit", "left"):
                                break                       # limit hit, or we left the GBG map
                            continue                        # province done → next target
                    else:
                        _escape_to_map(page)                # back out, commit nothing
                    break
                if _in_gbg(page):
                    skip.add(t.province_id)                  # remember: never reaches a fight
                    _skip_save(round_key, skip)              # persist for THIS round only
                print(f"  ⏭ {_name(names, t.province_id)} (id={t.province_id}): no army preview "
                      f"(guild HQ / ignore / not adjacent) — skipping henceforth", flush=True)
                _escape_to_map(page)                        # cancel dialog / close window
            if farm:
                print(f"\n[farm] {world} pass complete. Attrition now {reader.attrition_level} "
                      f"(limit {limit}).", flush=True)
            elif reached is not None:
                print(f"\n[attack] Full chain works end-to-end on province {reached}: map → open "
                      "→ Útok → battle screen. 🎯", flush=True)
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
                    ux, uy = utok_xy
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
    ap.add_argument("--world", default=None, help="world name/label (e.g. cz2); omit with --worlds")
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
    ap.add_argument("--ux", type=int, default=None, help="Útok button CSS x (canvas window)")
    ap.add_argument("--uy", type=int, default=None, help="Útok button CSS y (canvas window)")
    ap.add_argument("--abx", type=int, default=None, help="Automatická bitva button CSS x")
    ap.add_argument("--aby", type=int, default=None, help="Automatická bitva button CSS y")
    ap.add_argument("--grid", action="store_true",
                    help="just draw a labeled CSS grid on the current screen and screenshot")
    ap.add_argument("--click", action="store_true",
                    help="hover-click the Automatická bitva coord on the CURRENT screen (fights)")
    ap.add_argument("--repeat", type=int, default=1, help="with --click: fight this many times")
    ap.add_argument("--limit", type=int, default=None,
                    help="with --click: stop when attrition ≥ this")
    ap.add_argument("--inter", type=int, default=150, dest="inter",
                    help="with --click: ms to wait between fights")
    ap.add_argument("--reload-every", type=int, default=5, dest="reload_every",
                    help="with --click: press R (Reload units) every Nth fight; 0 disables")
    ap.add_argument("--watch", type=int, default=0,
                    help="listen N seconds for getBattleground refreshes and dump provinces")
    ap.add_argument("--reload", action="store_true", dest="reload_first",
                    help="reload the tab to force a fresh getBattleground, then dump targets")
    ap.add_argument("--enter", action="store_true", dest="enter_gbg",
                    help="click the city GBG entrance to open GBG + get fresh getBattleground")
    ap.add_argument("--gbg-x", type=int, default=1650, dest="gbg_x", help="GBG entrance CSS x")
    ap.add_argument("--gbg-y", type=int, default=250, dest="gbg_y", help="GBG entrance CSS y")
    ap.add_argument("--find-gbg", action="store_true", dest="find_gbg",
                    help="in the CITY: list DOM elements that could open GBG (viewport-independent)")
    ap.add_argument("--farm", action="store_true",
                    help="autonomous: enter GBG → fresh targets → fight each to the attrition limit")
    ap.add_argument("--pcts", default=None,
                    help="only attack these weakening %% (comma list, e.g. 20,40,60)")
    ap.add_argument("--passes", type=int, default=1,
                    help="with --farm: run this many self-healing passes (each re-enters GBG "
                         "from scratch — the watchdog; use a big number to run all day)")
    ap.add_argument("--worlds", default=None,
                    help="round-robin config JSON (per-world tab/limit/pcts); cycles all worlds")
    ap.add_argument("--cycles", type=int, default=1000,
                    help="with --worlds: how many full round-robin cycles (default: all day)")
    args = ap.parse_args(argv)

    if args.worlds:                                        # PARALLEL farming: one process per world
        import subprocess
        import sys
        cfg = json.load(open(args.worlds, encoding="utf-8"))
        gbg = cfg.get("gbg", {"x": 1650, "y": 250})
        worlds = cfg.get("worlds", [])
        print(f"[parallel] launching {len(worlds)} worlds concurrently, {args.cycles} passes each: "
              f"{[w['world'] for w in worlds]}", flush=True)
        procs = []
        for w in worlds:
            cmd = [sys.executable, "-m", "bap.forge.action.open_targets",
                   "--world", w["world"], "--tab", w.get("tab", w["world"]),
                   "--cdp", args.cdp, "--farm", "--passes", str(args.cycles),
                   "--inter", str(args.inter), "--reload-every", str(args.reload_every),
                   "--gbg-x", str(w.get("gbg_x", gbg["x"])),
                   "--gbg-y", str(w.get("gbg_y", gbg["y"]))]
            if w.get("limit") is not None:
                cmd += ["--limit", str(w["limit"])]
            if w.get("pcts"):
                cmd += ["--pcts", ",".join(str(x) for x in w["pcts"])]
            print(f"[parallel] → {w['world']}", flush=True)
            procs.append((w["world"], subprocess.Popen(cmd)))
            time.sleep(2)                                   # stagger CDP connects / GBG entries
        try:
            for _, p in procs:
                p.wait()
        except KeyboardInterrupt:
            print("\n[parallel] stopping all worlds…", flush=True)
            for _, p in procs:
                p.terminate()
        return 0
    pcts = None
    if args.pcts:
        pcts = {int(x) for x in args.pcts.replace(" ", "").split(",") if x}
    repeat = args.repeat
    if args.farm and repeat == 1:
        repeat = 300                                       # per-province fight cap for farming

    _skip = set()      # in-memory this session; run_open persists per ROUND (world+endsAt) to disk

    def _once():
        return run_open(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index, n=args.n,
                        debug=args.debug, overlay=args.overlay,
                        attack=args.attack or args.fight or args.farm,
                        fight=args.fight or args.farm, grid_only=args.grid, click_here=args.click,
                        repeat=repeat, limit=args.limit, inter_ms=args.inter,
                        reload_every=args.reload_every, watch=args.watch,
                        reload_first=args.reload_first, enter_gbg=args.enter_gbg,
                        gbg_pos=(args.gbg_x, args.gbg_y), farm=args.farm, pcts=pcts, skip=_skip,
                        find_gbg=args.find_gbg,
                        utok=((args.ux, args.uy) if args.ux and args.uy else None),
                        autobattle=((args.abx, args.aby) if args.abx and args.aby else None))

    # Watchdog: each pass is independent and re-establishes GBG from scratch (F5 + entrance),
    # so any breakage just ends the pass and the next one starts clean.
    passes = args.passes if args.farm else 1
    for i in range(passes):
        if passes > 1:
            print(f"\n===== farm pass {i + 1}/{passes} =====", flush=True)
        try:
            _once()
        except Exception as exc:  # noqa: BLE001
            print(f"[watchdog] pass {i + 1} failed: {exc} — restarting from scratch.", flush=True)
        if passes > 1 and i + 1 < passes:
            time.sleep(4)
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
