"""Locate the GBG entrance in the city by vision — the universal, FoE-Helper-free way in.

The entrance (``V_IronAge_BattlegroundDiamond`` — the golden Atlas-with-globe plaza, tooltip
"Cechovní bitvy / Guild Battlegrounds") is a canvas building: no DOM, and its pixel moves with
the player's zoom/scroll. Rather than ship a brittle hard-coded coordinate, we match its
reference sprite against a live screenshot (``detection/template_match``) and click where it
actually is — at any window size or zoom, on every world (the sprite is identical across them).

    # offline: test the matcher on a saved screenshot
    python -m bap.forge.action.gbg_entrance city.png
    python -m bap.forge.action.gbg_entrance city.png --template path/to/atlas_diamond.png --debug out.png

The live ``locate_entrance(page)`` screenshots the Playwright page and returns the click point;
``no-cover`` glue. The reference sprite lives at ``TEMPLATE_PATH`` (drop the crop there).
"""

from __future__ import annotations

import os

import cv2
import numpy as np

from bap.forge.detection.template_match import MatchResult, match_multiscale


def imread_unicode(path: str):
    """cv2.imread that survives non-ASCII paths (Windows 'Obrázky', 'Snímek', …). OpenCV's
    own imread mangles Unicode filenames, so read the bytes ourselves and decode."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)

# The reference sprite. Save the tight crop of the Atlas/diamond entrance here.
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "detection", "assets",
                             "gbg_entrance", "atlas_diamond.png")
# Below-centre so we land on the plaza/steps (clickable base), not the globe over the water.
CLICK_ANCHOR = (0.5, 0.60)
# Match must clear this to be trusted; below it we don't guess a wrong click.
MIN_SCORE = 0.45


def load_template(path: str | None = None) -> np.ndarray | None:
    p = os.path.abspath(path or TEMPLATE_PATH)
    if not os.path.exists(p):
        return None
    return imread_unicode(p)


def locate_entrance_in_image(image_bgr: np.ndarray, template_bgr: np.ndarray, *,
                             min_score: float = MIN_SCORE,
                             anchor: tuple[float, float] = CLICK_ANCHOR):
    """Return (click_x, click_y, MatchResult) for the entrance in a city screenshot, or None.

    The click point is the match box's :meth:`~MatchResult.anchor` (a touch below centre), so
    we hit the plaza rather than the tall statue."""
    m = match_multiscale(image_bgr, template_bgr, min_score=min_score)
    if m is None:
        return None
    cx, cy = m.anchor(*anchor)
    return cx, cy, m


def locate_entrance(page, *, template_path: str | None = None,
                    min_score: float = MIN_SCORE):  # pragma: no cover - live
    """Screenshot the Playwright ``page`` and locate the GBG entrance. Returns (x, y) in CSS
    pixels (screenshot is scaled back to viewport), or None if not confidently found."""
    tmpl = load_template(template_path)
    if tmpl is None:
        print(f"[entrance] no template at {TEMPLATE_PATH} — save the entrance crop there.",
              flush=True)
        return None
    png = page.screenshot()  # full viewport PNG bytes
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    found = locate_entrance_in_image(img, tmpl, min_score=min_score)
    if found is None:
        return None
    cx, cy, m = found
    # The screenshot may be at devicePixelRatio > 1; scale click coords back to CSS pixels.
    try:
        vw = page.viewport_size["width"] if page.viewport_size else img.shape[1]
    except Exception:
        vw = img.shape[1]
    sx = (vw / img.shape[1]) if img.shape[1] else 1.0
    out = (int(cx * sx), int(cy * sx))
    print(f"[entrance] found score={m.score:.3f} scale={m.scale:.2f} at screen {out}", flush=True)
    return out


def run(screenshot: str, template: str | None = None, debug: str | None = None,
        min_score: float = MIN_SCORE) -> int:
    img = imread_unicode(screenshot)
    if img is None:
        print(f"Could not read screenshot {screenshot}", flush=True)
        return 1
    tmpl = load_template(template)
    if tmpl is None:
        print(f"No template. Save the entrance crop to {os.path.abspath(TEMPLATE_PATH)} "
              "or pass --template.", flush=True)
        return 1
    found = locate_entrance_in_image(img, tmpl, min_score=0.0)  # report even weak, for tuning
    if found is None:
        print("No match at all (empty image/template?).", flush=True)
        return 1
    cx, cy, m = found
    ok = m.score >= min_score
    print(f"{'✅' if ok else '⚠️ '} score={m.score:.3f}  scale={m.scale:.2f}  "
          f"box={m.top_left}+{m.size}  click=({cx},{cy})", flush=True)
    if not ok:
        print(f"   below MIN_SCORE={min_score}: crop the template tighter to the building, or "
              "the entrance isn't on screen.", flush=True)
    if debug:
        x, y = m.top_left
        w, h = m.size
        vis = img.copy()
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 3)
        cv2.circle(vis, (cx, cy), 8, (0, 255, 0), -1)
        cv2.imwrite(debug, vis)
        print(f"   wrote {debug}", flush=True)
    return 0 if ok else 2


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    ap = argparse.ArgumentParser(
        prog="bap-forge-gbg-entrance",
        description="Vision-locate the GBG entrance (Atlas/diamond) in a city screenshot.")
    ap.add_argument("screenshot", help="a PNG/JPG screenshot of the city")
    ap.add_argument("--template", default=None, help="reference sprite (default: bundled asset)")
    ap.add_argument("--debug", default=None, help="write an annotated image here")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    args = ap.parse_args(argv)
    return run(args.screenshot, template=args.template, debug=args.debug,
               min_score=args.min_score)


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
