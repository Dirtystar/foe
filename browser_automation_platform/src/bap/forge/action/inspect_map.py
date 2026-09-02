"""Read-only reconnaissance of the live GBG map — how does the game represent provinces?

We keep hitting a wall calibrating map→screen by clicking, because the game only answers
(with a ``provinceId`` request) for *attackable* provinces. This tool asks the page directly,
without clicking anything, to find a better signal:

- Is the map a ``<canvas>`` (WebGL/pixi) or a tree of DOM elements?
- Are there DOM elements per province/sector/hex (→ we could read each province's screen
  rect straight from the DOM, no calibration at all)?
- What map/grid/camera-looking globals does the game expose?

Purely observational: it evaluates JS in the page and prints a report. No clicks, no writes.
``no-cover`` — it needs a live browser and only prints diagnostics.

Run:  python -m bap.forge.action.inspect_map --world cz2 --tab cz2
Paste the whole report back.
"""

from __future__ import annotations

import json

_JS_CANVASES = """
() => Array.from(document.querySelectorAll('canvas')).map(c => {
  const r = c.getBoundingClientRect();
  return {buf:[c.width,c.height], css:[Math.round(r.width),Math.round(r.height)],
          at:[Math.round(r.left),Math.round(r.top)], id:c.id||'',
          cls:(c.getAttribute('class')||'').slice(0,50)};
})
"""

_JS_DOM = """
() => {
  const rx = /province|sector|battleground|gbg|hexagon|\\bhex\\b|grid-?field|map-?tile/i;
  const hits = []; let scanned = 0;
  for (const el of document.querySelectorAll('*')) {
    scanned++;
    const cls = (el.getAttribute && el.getAttribute('class')) || '';
    const attrs = Array.from(el.attributes||[]).map(a=>a.name+'='+a.value).join(' ');
    const s = (el.id+' '+cls+' '+attrs);
    if (rx.test(s)) {
      const r = el.getBoundingClientRect();
      hits.push({tag:el.tagName, id:(el.id||'').slice(0,40), cls:(''+cls).slice(0,50),
                 rect:[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)],
                 data:Array.from(el.attributes||[]).filter(a=>/^data|id$/.test(a.name))
                       .map(a=>a.name+'='+a.value).slice(0,5)});
      if (hits.length>=30) break;
    }
  }
  return {scanned, count:hits.length, sample:hits};
}
"""

_JS_GLOBALS = """
() => {
  const rx = /gbg|battleground|grid|province|camera|viewport|foe|isometric|pixi|phaser/i;
  const out = {};
  for (const k of Object.keys(window)) {
    if (rx.test(k)) { try { out[k] = typeof window[k]; } catch(e) { out[k]='err'; } }
  }
  return out;
}
"""

_JS_FOE = """
() => {
  const out = {};
  const probe = p => { try { const v = eval(p); return typeof v + (v==null?' null':' ok'); }
                       catch(e){ return 'missing'; } };
  ['MainParser','FoEproxy','GuildBattlegrounds','ClientMessageService',
   'window.s','Runtime','GameMap','MapEntities','CFontAtlas'].forEach(p=>out[p]=probe(p));
  return out;
}
"""


def run_inspect(endpoint, world, *, tab=None, tab_index=None, connect=None):  # pragma: no cover - live
    from bap.forge.action.cdp_click import _select_page

    def _go(browser):
        page = _select_page(browser, index=tab_index, match=(tab or world))
        try:
            page.bring_to_front()
        except Exception:
            pass
        print(f"Inspecting {page.url}\n", flush=True)

        def _ev(label, js):
            try:
                val = page.evaluate(js)
            except Exception as exc:
                print(f"[{label}] evaluate failed: {exc}", flush=True)
                return None
            print(f"===== {label} =====", flush=True)
            print(json.dumps(val, indent=2, ensure_ascii=False)[:4000], flush=True)
            print("", flush=True)
            return val

        try:
            vw = page.evaluate("() => window.innerWidth")
            vh = page.evaluate("() => window.innerHeight")
            dpr = page.evaluate("() => window.devicePixelRatio")
            print(f"viewport {vw}x{vh}  devicePixelRatio={dpr}\n", flush=True)
        except Exception:
            pass

        _ev("CANVASES", _JS_CANVASES)
        dom = _ev("DOM province-like elements", _JS_DOM)
        _ev("map/grid GLOBALS", _JS_GLOBALS)
        _ev("FoE known objects", _JS_FOE)

        if dom and dom.get("count"):
            print("→ DOM province elements FOUND. If each has a stable id/data-id and a real "
                  "rect, we can read every province's screen position directly (no calibration).",
                  flush=True)
        else:
            print("→ No DOM province elements — the map is almost certainly a canvas. We'll need "
                  "the game's camera/grid state (globals above) or feedback navigation.",
                  flush=True)
        return dom

    if connect is not None:
        return _go(connect(endpoint))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return _go(p.chromium.connect_over_cdp(endpoint))


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap = argparse.ArgumentParser(
        prog="bap-forge-inspect",
        description="Read-only recon of how the GBG map represents provinces (no clicks).")
    ap.add_argument("--world", required=True, help="world name/label (e.g. cz2)")
    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT, help="Chrome CDP endpoint")
    ap.add_argument("--tab", default=None, help="tab: url/title contains this (default: world)")
    ap.add_argument("--tab-index", type=int, default=None, dest="tab_index")
    args = ap.parse_args(argv)
    try:
        run_inspect(args.cdp, args.world, tab=args.tab, tab_index=args.tab_index)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Inspect failed on {args.cdp}: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
