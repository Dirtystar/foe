"""Open GBG provinces by locating them via FoE Helper's marker arrow — no calibration.

For each target province: mark it (click its ``building-marker-btn`` in the DOM by id), read
the ``.building-marker-arrow`` translate = its screen point, clear the marker, click that
point on the canvas, and confirm the ``provinceId`` the game reports matches. Off-screen
sectors are panned into view first.

`bap-forge-locate --world cz2` opens the attackable "Next up" provinces to prove the primitive
before we build the fight loop on it. Live glue is ``no-cover``; the arrow parser
(`parse_marker_xy`) is unit-tested.
"""

from __future__ import annotations

import time

from bap.forge.gbg_data.marker import parse_marker_xy

_JS_ROWS = """
() => Array.from(document.querySelectorAll('tr.timer[data-id]')).map(tr => {
  const nameEl = tr.querySelector('.prov-name b');
  const bt = tr.querySelector('.battletype');
  const attr = tr.querySelector('.attrition-cell');
  return {id: parseInt(tr.getAttribute('data-id')),
          name: nameEl ? nameEl.textContent.trim() : '',
          attack: !!(bt && (bt.getAttribute('class')||'').indexOf('BTattack') >= 0),
          attrition: attr ? attr.textContent.trim() : '',
          hasMarker: !!tr.querySelector('.building-marker-btn')};
});
"""

_JS_READ_ARROW = ("() => { const a = document.querySelector('.building-marker-arrow');"
                  " return a ? (a.style.transform || a.getAttribute('style') || '') : null; }")
_JS_CLEAR = ("() => { const c = document.querySelector('.building-marker-close');"
             " if (c) { c.click(); return true; } return false; }")


def _click_marker_js(pid):
    return ("() => { const b = document.querySelector('button.building-marker-btn"
            f"[data-id=\"{pid}\"]'); if (!b) return false; b.click(); return true; }}")


def _viewport(page):  # pragma: no cover - live
    try:
        return (int(page.evaluate("() => window.innerWidth")),
                int(page.evaluate("() => window.innerHeight")))
    except Exception:
        return (2304, 1042)


def _escape_to_map(page):  # pragma: no cover - live
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(250)


def _pan(page, dx, dy, vw, vh):  # pragma: no cover - live
    sx, sy = vw / 2, vh / 2
    try:
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx + dx, sy + dy, steps=12)
        page.mouse.up()
    except Exception:
        pass
    page.wait_for_timeout(300)


def locate_province(page, pid, timeout=2.5):  # pragma: no cover - live
    """Mark province ``pid`` and return its screen (x, y) from the arrow, or None."""
    if not page.evaluate(_click_marker_js(pid)):
        return None
    xy = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(150)
        xy = parse_marker_xy(page.evaluate(_JS_READ_ARROW))
        if xy is not None:
            break
    return xy


def clear_marker(page):  # pragma: no cover - live
    try:
        page.evaluate(_JS_CLEAR)
        page.wait_for_timeout(150)
    except Exception:
        pass


def _r(v):  # pragma: no cover
    return int(round(v))


def open_via_marker(page, clicker, latest, pid, vw, vh, max_pans=4):  # pragma: no cover - live
    """Locate ``pid`` via its marker, pan it on-screen if needed, click it, confirm provinceId.
    Returns the screen point clicked on success, else None."""
    xy = locate_province(page, pid)
    if xy is None:
        return None
    margin = 80
    pans = 0
    while not (margin <= xy[0] <= vw - margin and margin <= xy[1] <= vh - margin) and pans < max_pans:
        dx = max(-vw * 0.6, min(vw * 0.6, vw / 2 - xy[0]))
        dy = max(-vh * 0.6, min(vh * 0.6, vh / 2 - xy[1]))
        _pan(page, dx, dy, vw, vh)
        pans += 1
        new = parse_marker_xy(page.evaluate(_JS_READ_ARROW))  # arrow re-anchors after we pan
        if new is None:
            new = locate_province(page, pid)
        if new is None:
            break
        xy = new
    clear_marker(page)                     # so the arrow SVG can't intercept our click
    latest["pid"] = None
    clicker.click_xy(xy[0], xy[1])
    deadline = time.time() + 4.0
    while time.time() < deadline:
        page.wait_for_timeout(150)
        if latest["pid"] is not None:
            break
    hit = latest["pid"]
    _escape_to_map(page)
    return xy if hit == pid else None


def run_locate(endpoint, world, *, tab=None, tab_index=None, n=3, attack_only=True,
               connect=None):  # pragma: no cover - live
    from bap.forge.action.cdp_click import CdpClicker, _select_page
    from bap.forge.gbg_data.parser import parse_province_id_from_game_json

    def _go(browser):
        page = _select_page(browser, index=tab_index, match=(tab or world))
        try:
            page.bring_to_front()
        except Exception:
            pass
        latest = {"pid": None}

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

        page.on("request", _on_request)

        rows = page.evaluate(_JS_ROWS)
        rows = [r for r in rows if r.get("hasMarker")]
        if attack_only:
            rows = [r for r in rows if r.get("attack")]
        if not rows:
            print("No markable attackable provinces in the FoE Helper 'Next up' box. Open the "
                  "GBG map with that box visible, or pass --all to include defence.", flush=True)
            return None
        vw, vh = _viewport(page)
        print(f"Viewport {vw}x{vh}. {len(rows)} markable targets; opening up to {n}.", flush=True)

        clicker = CdpClicker(page)
        targets = rows[:n]
        ok = 0
        for r in targets:
            pid = r["id"]
            scr = open_via_marker(page, clicker, latest, pid, vw, vh)
            mark = "✅" if scr else "❌"
            where = f"clicked ({_r(scr[0])},{_r(scr[1])})" if scr else "provinceId mismatch/none"
            print(f"  {mark} {r['name']} (id={pid}, {r['attrition']}): {where}", flush=True)
            if scr:
                ok += 1
        print(f"\n{ok}/{len(targets)} opened correctly via marker. "
              + ("Navigation solved — no calibration! 🎯" if ok == len(targets)
                 else "Some misses — send the log."), flush=True)
        try:
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
        prog="bap-forge-locate",
        description="Open GBG provinces via FoE Helper's marker arrow (no calibration).")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz2)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    ap.add_argument("-n", type=int, default=3, help="how many provinces to open")
    ap.add_argument("--all", action="store_true", help="include defence provinces, not just attack")
    args = ap.parse_args(argv)
    try:
        r = run_locate(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index, n=args.n,
                       attack_only=not args.all)
        return 0 if r is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Locate failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
