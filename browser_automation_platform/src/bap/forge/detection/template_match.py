"""Multi-scale template matching — find a known sprite in a screenshot at any zoom.

The city is a WebGL canvas, so a building has no DOM and its on-screen pixel depends on the
player's zoom/scroll. But its **sprite is stable** (same art on every world). So to locate a
fixed building (e.g. the GBG entrance, ``V_IronAge_BattlegroundDiamond`` — the golden Atlas
plaza) we match its reference sprite against the screenshot across a range of scales and take
the best-scoring placement. Scale-sweeping is what makes it survive zoom; ``TM_CCOEFF_NORMED``
keeps the score comparable across scales so the best one wins honestly.

Pure OpenCV + NumPy, no browser and no game state — unit-testable. The live capture and the
click-point mapping live in ``action/gbg_entrance.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class MatchResult:
    """Best placement of a template in an image."""

    score: float                 # TM_CCOEFF_NORMED peak, [-1, 1]; higher = better
    top_left: tuple[int, int]    # (x, y) of the match box in the image
    size: tuple[int, int]        # (w, h) of the scaled template
    scale: float                 # template scale that won

    @property
    def center(self) -> tuple[int, int]:
        x, y = self.top_left
        w, h = self.size
        return (x + w // 2, y + h // 2)

    def anchor(self, fx: float = 0.5, fy: float = 0.5) -> tuple[int, int]:
        """A point inside the match box at fractional (fx, fy) — e.g. (0.5, 0.62) aims a bit
        below centre, onto a building's plaza/base rather than a tall statue's top."""
        x, y = self.top_left
        w, h = self.size
        return (int(x + fx * w), int(y + fy * h))


def _default_scales() -> list[float]:
    # 0.25 → 1.60 in ~7% steps: a reference sprite cropped from a zoomed-in view can appear
    # much smaller in a normal screenshot, so sweep well below 1.0. 1.0 (native) always included.
    out, s = {1.0}, 0.25
    while s <= 1.60001:
        out.add(round(s, 3))
        s *= 1.07
    return sorted(out)


def match_multiscale(image_bgr: np.ndarray, template_bgr: np.ndarray, *,
                     scales=None, min_score: float = 0.0) -> MatchResult | None:
    """Best multi-scale placement of ``template_bgr`` in ``image_bgr``.

    Sweeps ``scales`` (default ~0.45–1.6), resizing the *template* each time, and keeps the
    highest ``TM_CCOEFF_NORMED`` peak. Returns ``None`` if nothing reaches ``min_score`` or the
    template never fits. Inputs are BGR uint8 (as OpenCV loads them)."""
    if image_bgr is None or template_bgr is None:
        return None
    ih, iw = image_bgr.shape[:2]
    th0, tw0 = template_bgr.shape[:2]
    if ih == 0 or iw == 0 or th0 == 0 or tw0 == 0:
        return None

    best: MatchResult | None = None
    for sc in (scales or _default_scales()):
        tw, th = max(1, int(tw0 * sc)), max(1, int(th0 * sc))
        if tw > iw or th > ih or tw < 8 or th < 8:
            continue
        tmpl = cv2.resize(template_bgr, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(image_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
        _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
        if best is None or maxv > best.score:
            best = MatchResult(score=float(maxv), top_left=(int(maxl[0]), int(maxl[1])),
                               size=(tw, th), scale=float(sc))
    if best is None or best.score < min_score:
        return None
    return best


__all__ = ["MatchResult", "match_multiscale"]
