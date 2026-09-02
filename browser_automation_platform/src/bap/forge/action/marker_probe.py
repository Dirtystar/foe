"""Discover how FoE Helper's "Mark sector on the map" arrow appears in the DOM.

The GBG map is a canvas, so a province has no DOM node — but FoE Helper draws a floating
arrow *at* a sector's on-screen position when you press its marker button. If that arrow is a
DOM element, we can read its rect → the province's screen point, pair it with the province's
map-space flag (both keyed by the same provinceId = the row's ``data-id``), and solve the
map→screen transform automatically. This probe finds the arrow's DOM signature so we can read
it reliably.

It: (1) reads the FoE Helper "Next up" rows (provinceId, name, attrition%, battle type),
(2) tags every existing DOM node, (3) clicks one province's marker button *via the DOM* (no
coordinates), (4) prints every node that newly appeared over the map — the arrow is among
them. Read-only w.r.t. game state (marker is a client-side overlay). ``no-cover`` — live.

Run:  python -m bap.forge.action.marker_probe --world cz2 --tab cz2
"""

from __future__ import annotations

import json

# The FoE Helper "Next up" table rows: data-id = provinceId, plus name/attrition/battletype.
_JS_ROWS = """
() => Array.from(document.querySelectorAll('tr.timer[data-id]')).map(tr => {
  const nameEl = tr.querySelector('.prov-name b');
  const bt = tr.querySelector('.battletype');
  const attr = tr.querySelector('.attrition-cell');
  const owner = tr.querySelector('.prov-name');
  const r = tr.getBoundingClientRect();
  return {id: tr.getAttribute('data-id'),
          name: nameEl ? nameEl.textContent.trim() : '',
          battletype: bt ? (bt.getAttribute('class') || '').replace('battletype','').trim() : '',
          attrition: attr ? attr.textContent.trim() : '',
          owner: owner ? (owner.getAttribute('data-original-title') || '') : '',
          locked: tr.className.indexOf('secure') >= 0,
          hasMarker: !!tr.querySelector('.building-marker-btn'),
          rowVisible: r.width > 0};
});
"""

_JS_TAG_EXISTING = "() => { document.querySelectorAll('body *').forEach(e => e.setAttribute('data-bapseen','1')); return true; }"


def _js_click_marker(pid):
    return ("() => { const b = document.querySelector('button.building-marker-btn"
            f"[data-id=\"{pid}\"]'); if (!b) return 'no-button'; b.click(); return 'clicked'; }}")


# Every node that appeared after the click (the arrow overlay is among these).
_JS_NEW_NODES = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('body *:not([data-bapseen])')) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    out.push({tag: el.tagName,
              cls: (el.getAttribute('class') || '').slice(0, 50),
              id: (el.id || '').slice(0, 40),
              img: (el.getAttribute('src') || '').split('/').pop().slice(0, 40),
              pos: st.position, z: st.zIndex,
              rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
              html: (el.outerHTML || '').replace(/\\s+/g, ' ').slice(0, 160)});
  }
  return out.slice(0, 50);
}
"""


def run_marker_probe(endpoint, world, *, tab=None, tab_index=None, pid=None,
                     connect=None):  # pragma: no cover - live
    from bap.forge.action.cdp_click import _select_page

    def _go(browser):
        page = _select_page(browser, index=tab_index, match=(tab or world))
        try:
            page.bring_to_front()
        except Exception:
            pass
        print(f"Marker probe on {page.url}\n", flush=True)

        rows = page.evaluate(_JS_ROWS)
        print("===== FoE Helper 'Next up' rows =====", flush=True)
        print(json.dumps(rows, indent=2, ensure_ascii=False)[:3000], flush=True)
        if not rows:
            print("\nNo FoE Helper rows found. Open the GBG map with the FoE Helper GBG box "
                  "visible (the province table on the right), then re-run.", flush=True)
            return None

        # choose the province to mark: caller's --pid, else the first with a marker button
        target = None
        if pid is not None:
            target = next((r for r in rows if str(r.get("id")) == str(pid)), None)
        if target is None:
            target = next((r for r in rows if r.get("hasMarker")), None)
        if target is None:
            print("\nNo row has a 'Mark sector on the map' button.", flush=True)
            return None
        tid = target["id"]
        print(f"\nMarking province id={tid} ({target.get('name')}, {target.get('attrition')}, "
              f"{target.get('battletype')})…", flush=True)

        page.evaluate(_JS_TAG_EXISTING)
        res = page.evaluate(_js_click_marker(tid))
        print(f"  marker button click → {res}", flush=True)
        page.wait_for_timeout(1500)

        new_nodes = page.evaluate(_JS_NEW_NODES)
        print("\n===== NEW DOM nodes after marking (arrow should be here) =====", flush=True)
        print(json.dumps(new_nodes, indent=2, ensure_ascii=False)[:4500], flush=True)

        # heuristic: overlay nodes sitting over the map (left of the sidebar, non-zero size)
        over_map = [n for n in new_nodes
                    if n["rect"][2] > 0 and n["rect"][3] > 0 and n["rect"][0] < 1740]
        print("\n===== candidates over the map =====", flush=True)
        if over_map:
            for n in over_map:
                cx = n["rect"][0] + n["rect"][2] // 2
                cy = n["rect"][1] + n["rect"][3] // 2
                print(f"  {n['tag']} .{n['cls']} img={n['img']} pos={n['pos']} z={n['z']} "
                      f"→ centre ({cx},{cy})", flush=True)
            print("\n→ If one of these sits at the sector, its centre is province "
                  f"{tid}'s screen position. Tell Radek which class/img it is.", flush=True)
        else:
            print("  none — the arrow may be drawn inside the canvas (WebGL), or the marker "
                  "toggled off. Try --pid for a province that's currently on-screen.", flush=True)
        return new_nodes

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap = argparse.ArgumentParser(
        prog="bap-forge-marker",
        description="Discover FoE Helper's sector-marker arrow in the DOM (read-only).")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz2)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    ap.add_argument("--pid", default=None, help="province id (row data-id) to mark; "
                    "default: first row with a marker button")
    args = ap.parse_args(argv)
    try:
        run_marker_probe(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index,
                         pid=args.pid)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Marker probe failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
