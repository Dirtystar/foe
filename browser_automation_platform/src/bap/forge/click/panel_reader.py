"""Independent province/detail-panel percentage reader (Milestone 6A.1).

After the single click opens the sector panel, this reads the weakening percentage
shown **in the panel** as a *second, independent* observation — it never takes the
map classifier's result as input. Independence comes from two things:

1. **Different pixels.** It reads the panel's fixed weakening pill
   (`PANEL_PILL_CENTER`, scaled to the capture resolution), not the map badge.
2. **A signal the map path never uses.** The map classifier is an OCR-free
   *grayscale* crop-cosine; this reader adds an independent **HSV colour-group**
   check (blue → 20/40, red → 80/100, green → 60). Colour cannot separate 20 from
   40 (both blue) — only the value read does that — but colour catches a gross
   family error (e.g. a map "20" whose panel pill is red).

**Fail-closed.** Anything uncertain — no confident percentage, similarity below the
bar, unconfirmed, or a colour/percentage contradiction — yields ``ok=False`` with a
reason, which the controller treats as a hard STOP. Classes are **never collapsed**:
80 and 100 are reported distinctly, as are 20 and 40.

The percentage *technique/bank* is injected (the same `PercentClassifier` the app
already builds), so this module stays testable and does not modify the classifier.
A future dedicated panel-exemplar bank / digit reader can replace the injected
classifier without touching the controller.
"""

from __future__ import annotations

from dataclasses import dataclass

from bap.forge.detection.classify import percent_patch
from bap.forge.detection.detector import PANEL_PILL_CENTER
from bap.forge.detection.scan import MIN_PCT_SIM
from bap.forge.labeling.model import VALID_PCTS

# Colour family → the percentages that legitimately wear that colour. Used only as a
# consistency guard against a gross family error; never to *infer* the value.
COLOR_FAMILY = {
    "blue": frozenset({20, 40}),
    "green": frozenset({60}),
    "red": frozenset({80, 100}),
}

# Reference resolution the fixed panel-pill coordinate was measured at.
_REF_W, _REF_H = 1920, 1080


@dataclass(frozen=True)
class PanelReading:
    """The independent panel read. ``ok`` means a confident, colour-consistent
    percentage was read and may be compared to the map prediction."""

    ok: bool
    pct: int | None
    confidence: float          # cosine similarity 0..1 (0 when unread)
    color_group: str           # "blue" | "green" | "red" | "other" | "none"
    reason: str
    pill_center: tuple[int, int]
    crop_bgr: object | None = None   # BGR pill crop, for diagnostics / future exemplars

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "pct": self.pct, "confidence": round(self.confidence, 4),
            "color_group": self.color_group, "reason": self.reason,
            "pill_center": list(self.pill_center),
        }


def scaled_pill_center(width: int, height: int) -> tuple[int, int]:
    """The panel pill centre for a capture of this size (the fixed 1920x1080 point
    scaled by the capture's dimensions)."""
    if width <= 0 or height <= 0:
        return PANEL_PILL_CENTER
    px, py = PANEL_PILL_CENTER
    return (int(round(px * width / _REF_W)), int(round(py * height / _REF_H)))


def _dominant_color_group(crop_bgr) -> str:
    """The dominant saturated hue family in a BGR crop, or 'none' when there are too
    few saturated pixels to judge."""
    try:
        import cv2
        import numpy as np
    except Exception:  # pragma: no cover - vision libs always present in app
        return "none"
    if crop_bgr is None or crop_bgr.size == 0:
        return "none"
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = (sat >= 80) & (val >= 60)
    n = int(mask.sum())
    if n < max(8, crop_bgr.shape[0] * crop_bgr.shape[1] // 40):
        return "none"
    h = hue[mask].astype("int32")
    red = int(((h <= 12) | (h >= 168)).sum())
    blue = int(((h >= 100) & (h <= 135)).sum())
    green = int(((h >= 40) & (h < 100)).sum())
    best = max((red, "red"), (blue, "blue"), (green, "green"), key=lambda t: t[0])
    # Require the winner to be a clear plurality, else "other".
    if best[0] < n * 0.5:
        return "other"
    return best[1]


class PanelReader:
    """Reads the panel weakening percentage independently of the map result."""

    def __init__(self, classifier, *, min_sim: float = MIN_PCT_SIM,
                 pill_center: tuple[int, int] | None = None):
        self._clf = classifier
        self._min_sim = float(min_sim)
        self._pill_override = pill_center

    def read(self, image_bgr) -> PanelReading:
        """Read the panel pill percentage + colour group from a fresh BGR capture."""
        try:
            import numpy as np  # noqa: F401
        except Exception:  # pragma: no cover
            pass
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            return PanelReading(False, None, 0.0, "none", "no image", PANEL_PILL_CENTER)
        h, w = image_bgr.shape[:2]
        cx, cy = self._pill_override or scaled_pill_center(w, h)

        # Independent colour-group signal from a small BGR crop around the pill.
        r = 34
        x0, y0 = max(0, cx - r), max(0, cy - r)
        x1, y1 = min(w, cx + r), min(h, cy + r)
        crop = image_bgr[y0:y1, x0:x1] if (x1 > x0 and y1 > y0) else None
        color_group = _dominant_color_group(crop)

        # Independent percentage read on the panel pill (its own observation).
        if self._clf is None or len(self._clf) == 0:
            return PanelReading(False, None, 0.0, color_group,
                                "panel percentage bank empty — cannot confirm (UNKNOWN)",
                                (cx, cy), crop)
        patch = percent_patch(image_bgr, cx, cy)
        if patch is None:
            return PanelReading(False, None, 0.0, color_group,
                                "panel pill outside the captured frame (UNKNOWN)",
                                (cx, cy), crop)
        pct, sim = self._clf.predict(patch)
        confirm = getattr(self._clf, "confirmed", None)
        confirmed = confirm(patch) if confirm is not None else True

        if pct is None or pct not in VALID_PCTS:
            return PanelReading(False, pct, float(sim), color_group,
                                "panel percentage UNKNOWN — no confident class", (cx, cy), crop)
        if sim < self._min_sim or not confirmed:
            return PanelReading(False, pct, float(sim), color_group,
                                f"panel percentage {pct}% below acceptance "
                                f"(sim {sim:.2f} < {self._min_sim:.2f} or unconfirmed) — UNKNOWN",
                                (cx, cy), crop)

        # Colour/percentage consistency: a *known* family that excludes the read
        # value is a gross error → fail closed. An indeterminate colour does not by
        # itself veto the value (colour cannot resolve 20 vs 40 anyway).
        fam = COLOR_FAMILY.get(color_group)
        if fam is not None and pct not in fam:
            return PanelReading(False, pct, float(sim), color_group,
                                f"panel colour {color_group} inconsistent with {pct}% — UNKNOWN",
                                (cx, cy), crop)

        return PanelReading(True, pct, float(sim), color_group,
                            f"panel {pct}% at similarity {sim:.2f}, colour {color_group}",
                            (cx, cy), crop)


__all__ = ["PanelReader", "PanelReading", "scaled_pill_center", "COLOR_FAMILY"]
