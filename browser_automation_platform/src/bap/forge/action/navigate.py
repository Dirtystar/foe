"""Reach and open any GBG province on a scrolling map — robustly, with self-correction.

The map is bigger than the viewport, does not re-centre on open, but can be dragged. So we
keep a running transform (:class:`MapNavigator`): fixed ``scale`` (bootstrapped from two app
clicks) plus an ``offset`` we keep current as we drag. To open a target we compute its screen
point, **drag** it on-screen if needed, click, and read the ``provinceId`` the game reports:
if it's the target we're done; if it's a different province we **learn the true offset from
it** and retry (converges in 1-2 clicks). Off-screen targets are reached by dragging.

`bap-forge-verify --world cz6` bootstraps and then opens a few provinces to prove it hits the
right ones. Live glue is ``no-cover``; the geometry (`MapNavigator`) is unit-tested.
"""

from __future__ import annotations

import time

from bap.forge.gbg_data.navigator import MapNavigator, estimate_scale


def _viewport(page):  # pragma: no cover - live
    try:
        return (int(page.evaluate("() => window.innerWidth")),
                int(page.evaluate("() => window.innerHeight")))
    except Exception:
        return (1536, 695)


def _escape_to_map(page):  # pragma: no cover - live
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(250)


def _pan(page, dx, dy, vw, vh):  # pragma: no cover - live
    """Drag the map by (dx, dy) from the viewport centre."""
    sx, sy = vw / 2, vh / 2
    try:
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx + dx, sy + dy, steps=12)
        page.mouse.up()
    except Exception:
        pass
    page.wait_for_timeout(300)


def _click_read_pid(page, clicker, latest, pt, timeout=4.0):  # pragma: no cover - live
    """Click ``pt``, wait for the province the game opens, then Escape back to the map."""
    latest["pid"] = None
    clicker.click_xy(pt[0], pt[1])
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(150)
        if latest["pid"] is not None:
            break
    pid = latest["pid"]
    _escape_to_map(page)
    return pid


def _bootstrap(page, clicker, latest, flags, vw, vh):  # pragma: no cover - live
    """Estimate scale by clicking two spread points and seeing which provinces open."""
    probes = [(vw * 0.35, vh * 0.5), (vw * 0.65, vh * 0.5),
              (vw * 0.5, vh * 0.35), (vw * 0.5, vh * 0.65)]
    anchors = []
    for p in probes:
        pid = _click_read_pid(page, clicker, latest, p)
        if pid is not None and pid in flags:
            anchors.append((p, flags[pid]))
            print(f"  anchor: click {(_r(p[0]), _r(p[1]))} → province {pid}", flush=True)
        if len(anchors) == 2:
            break
    if len(anchors) < 2:
        return None
    (s1, f1), (s2, f2) = anchors
    scale = estimate_scale(s1, f1, s2, f2)
    if not scale:
        return None
    nav = MapNavigator(scale=scale)
    nav.learn_offset(s2, f2)
    return nav


def _r(v):  # pragma: no cover
    return int(round(v))


def open_province(page, clicker, nav, latest, flags, target_id, vw, vh,
                  max_tries=5):  # pragma: no cover - live
    """Open ``target_id``: drag it on-screen if needed, click, self-correct from feedback."""
    tf = flags.get(target_id)
    if tf is None:
        return None
    for _ in range(max_tries):
        for _ in range(5):                         # bring on-screen by dragging
            scr = nav.screen_for(tf)
            if nav.on_screen(scr, vw, vh):
                break
            dx, dy = nav.drag_to_center(tf, vw, vh)
            dx = max(-vw * 0.6, min(vw * 0.6, dx))
            dy = max(-vh * 0.6, min(vh * 0.6, dy))
            _pan(page, dx, dy, vw, vh)
            nav.apply_drag(dx, dy)
        scr = nav.screen_for(tf)
        pid = _click_read_pid(page, clicker, latest, scr)
        if pid == target_id:
            return scr
        if pid is not None and pid in flags:
            nav.learn_offset(scr, flags[pid])      # correct from the province we actually hit
        else:
            nav.apply_drag(25, 25)                 # nothing opened — nudge and retry
    return None


def run_verify(endpoint, world, *, tab=None, tab_index=None, n=3,
               connect=None):  # pragma: no cover - live
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
        flags = layout.flags
        vw, vh = _viewport(page)
        print(f"Map: {len(flags)} provinces. Viewport {vw}x{vh}. Be on the GBG map.", flush=True)

        _escape_to_map(page)
        nav = _bootstrap(page, clicker=CdpClicker(page), latest=latest, flags=flags,
                         vw=vw, vh=vh)
        if nav is None:
            print("Bootstrap failed — could not open two provinces to estimate scale. Make "
                  "sure you're on the GBG map with attackable provinces visible.", flush=True)
            return None
        print(f"Bootstrapped: scale={nav.scale:.4f}", flush=True)

        clicker = CdpClicker(page)
        targets = [t.province_id for t in reader.targets()][:n] if reader.snapshot else []
        if not targets:
            targets = list(flags)[:n]
        print(f"Opening targets {targets} (drag + self-correct)…", flush=True)
        ok = 0
        for tid in targets:
            scr = open_province(page, clicker, nav, latest, flags, tid, vw, vh)
            mark = "✅" if scr else "❌"
            print(f"  {mark} province {tid}: "
                  + (f"opened at ({_r(scr[0])},{_r(scr[1])})" if scr else "could not open"),
                  flush=True)
            if scr:
                ok += 1
        print(f"\n{ok}/{len(targets)} opened correctly. "
              + ("Robust navigation works! 🎯" if ok == len(targets)
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
        prog="bap-forge-verify",
        description="Reach and open provinces on the scrolling map (bootstrap + self-correct).")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz6)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    ap.add_argument("-n", type=int, default=3, help="how many provinces to open")
    args = ap.parse_args(argv)
    try:
        r = run_verify(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index, n=args.n)
        return 0 if r is not None else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Verify failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
