"""Weakening-badge detector.

Two stages, tuned against the human-confirmed grading set:

  1. **Locate (recall)** — segment the badge's red attrition arrow (bright *and*
     dark red; the true arrows are darker than they look — value ~95) inside the
     game region and take blob centroids. This finds candidate positions across
     map biomes and pill backgrounds. Colour alone has poor precision (province
     name-banners are red too), so it is only a proposal step.
  2. **Confirm (precision)** — multi-scale, background-masked template match of a
     bank of real emblem crops. True emblems score distinctly higher than banner
     reds (measured medians ~0.73 vs ~0.36), so a score threshold + NMS keeps the
     badges and drops the banners. Confidence is the emblem score.

Reported centres are shifted by a fitted offset so they land on the badge centre
a human marks (the arrow sits ~12 px left of it). The side-panel pill is a fixed
state signal, reported separately. Pure over pixels — no clicking, no page access.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

try:
    import cv2
    import numpy as np

    _CV = True
except Exception:  # pragma: no cover - environment dependent
    _CV = False

_ASSETS = Path(__file__).with_name("assets")

DEFAULT_REGION = (440, 500, 1915, 1075)  # x0, y0, x1, y1 for a 1920x1080 capture
PANEL_PILL_CENTER = (1469, 773)
PANEL_PILL_RADIUS = 60
TEMPLATE_SIZE = 40  # emblem template square edge


@dataclass(frozen=True)
class Detection:
    """One detected badge. Centre and bbox are original-image pixels;
    `confidence` in [0,1]; `pct` is None until the classifier runs; `kind` is
    "map" (a target) or "panel" (the fixed side-panel state signal)."""

    cx: int
    cy: int
    x: int
    y: int
    w: int
    h: int
    confidence: float
    pct: int | None = None
    kind: str = "map"

    def with_pct(self, pct: int | None) -> "Detection":
        return replace(self, pct=pct)

    @property
    def center(self) -> tuple[int, int]:
        return (self.cx, self.cy)

    def to_dict(self) -> dict:
        return {
            "cx": self.cx, "cy": self.cy,
            "bbox": [self.x, self.y, self.w, self.h],
            "confidence": round(self.confidence, 4),
            "pct": self.pct, "kind": self.kind,
        }


@dataclass
class DetectResult:
    """Full stage-1 → stage-2 detection trace for one image. ``detections`` are
    the kept badges (post-threshold, post-NMS); ``candidates`` records **every**
    stage-1 colour proposal with its best emblem score and why it was kept or
    rejected — for the Vision Debugger's diagnosis, never for acting."""

    detections: list["Detection"] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)  # {cx,cy,score,kept,reason}


def _emblem_mask(tpl):
    """Mask out the emblem template's fairly-uniform blue pill background so the
    match keys on the crossbow/sword/arrow foreground and generalises to
    brown/over-terrain pills."""
    hsv = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV)
    hue, sat = hsv[..., 0], hsv[..., 1]
    blue_bg = (hue >= 95) & (hue <= 125) & (sat > 80)
    mask = (~blue_bg).astype("uint8") * 255
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), "uint8"))


def load_bundled_templates() -> list:
    """Load (template, mask) pairs shipped under assets/emblems/."""
    if not _CV:  # pragma: no cover
        return []
    out = []
    for p in sorted((_ASSETS / "emblems").glob("*.png")):
        t = cv2.imread(str(p))
        if t is not None:
            out.append((t, _emblem_mask(t)))
    return out


def build_templates_from_labels(frames_dir, labels_path, *, exclude_file: str | None = None) -> list:
    """Crop emblem (template, mask) pairs from the reviewed ground-truth badges,
    optionally excluding one frame — used for leave-one-frame-out evaluation so a
    frame is never scored with a template cut from itself."""
    if not _CV:  # pragma: no cover
        return []
    from bap.forge.labeling.model import LabelStore

    frames_dir = Path(frames_dir)
    store = LabelStore.load(labels_path)
    out = []
    s = TEMPLATE_SIZE
    for name in store.files():
        if name == exclude_file:
            continue
        fl = store.get(name)
        if fl is None or not fl.reviewed:
            continue
        img = cv2.imread(str(frames_dir / name))
        if img is None:
            continue
        for b in fl.badges:
            ax, ay = b.cx - 12, b.cy  # arrow centre (click centre minus the offset)
            x0, y0 = ax - s // 2, ay - s // 2
            if x0 < 0 or y0 < 0 or x0 + s > img.shape[1] or y0 + s > img.shape[0]:
                continue
            t = img[y0:y0 + s, x0:x0 + s]
            out.append((t, _emblem_mask(t)))
    return out


class BadgeDetector:
    def __init__(
        self,
        *,
        templates: list | None = None,
        region: tuple[int, int, int, int] = DEFAULT_REGION,
        scales: tuple[float, ...] = (0.85, 1.0, 1.15),
        score_threshold: float = 0.55,
        sat_min: int = 140,
        val_min: int = 80,
        min_area: int = 5,
        max_area: int = 400,
        max_side: int = 40,
        nms_radius: int = 24,
        # Arrow-centre → human-marked badge-centre offset, fitted on the grading
        # set (the arrow sits ~16 px left of where a human clicks the badge).
        center_offset: tuple[int, int] = (16, 0),
    ) -> None:
        if not _CV:  # pragma: no cover
            raise RuntimeError("BadgeDetector requires OpenCV (the 'vision' extra).")
        self._templates = templates if templates is not None else load_bundled_templates()
        self._region = region
        self._scales = scales
        self._threshold = score_threshold
        self._sat_min, self._val_min = sat_min, val_min
        self._min_area, self._max_area, self._max_side = min_area, max_area, max_side
        self._nms_radius = nms_radius
        self._offset = center_offset

    # --- public API ---------------------------------------------------------

    def detect(self, image, region: tuple[int, int, int, int] | None = None) -> list[Detection]:
        """Kept map badges. ``region`` (x0,y0,x1,y1) overrides the search area —
        Test Scan passes the calibrated battle-map ROI so the whole visible map
        is analyzed rather than a fixed sub-rectangle."""
        return self.scan(image, region=region).detections

    def scan(self, image, region: tuple[int, int, int, int] | None = None) -> DetectResult:
        """Full trace: every stage-1 colour candidate recorded EXACTLY ONCE with
        its colour-prior area, best emblem/template score, ROI-local coordinates,
        and final keep/reject reason, plus the kept detections after threshold +
        NMS. A candidate that clears the template threshold but is then dropped by
        NMS is reported once, as NMS-suppressed."""
        img = self._as_image(image)
        if img is None or not self._templates:
            return DetectResult()
        px, py = PANEL_PILL_CENTER
        pr2 = PANEL_PILL_RADIUS * PANEL_PILL_RADIUS
        rx0, ry0 = (region[0], region[1]) if region is not None else self._region[:2]
        entries: list[dict] = []
        for cx, cy, area in self._arrow_candidates(img, region):
            e = {"cx": cx, "cy": cy, "roi_cx": cx - rx0, "roi_cy": cy - ry0,
                 "color_area": int(area), "template_score": None, "confirmed": False,
                 "kept": False, "reason": ""}
            if (cx - px) ** 2 + (cy - py) ** 2 <= pr2:
                e["reason"] = "inside fixed panel-pill exclusion zone"
                entries.append(e)
                continue  # the fixed panel pill is reported separately
            score = self._emblem_score(img, cx, cy)
            e["template_score"] = round(score, 4)
            if score >= self._threshold:
                e["confirmed"] = True
                e["_det"] = self._make(cx, cy, score, "map")
                e["reason"] = "template-confirmed"
            else:
                e["reason"] = f"template score {score:.2f} < {self._threshold:.2f}"
            entries.append(e)

        confirmed = [e for e in entries if e.get("_det") is not None]
        kept = self._nms([e["_det"] for e in confirmed])
        kept_ids = {id(d) for d in kept}
        for e in confirmed:
            if id(e["_det"]) in kept_ids:
                e["kept"] = True
                e["reason"] = "template-confirmed; kept"
            else:
                e["reason"] = "suppressed by NMS (near a stronger badge)"
        candidates = [{k: v for k, v in e.items() if k != "_det"} for e in entries]
        return DetectResult(detections=kept, candidates=candidates)

    def score_at(self, image, cx: int, cy: int) -> float:
        """Public best masked-emblem score in the window around an arrow centre.
        Used by the scan to score the fixed panel-pill spot for diagnosis."""
        img = self._as_image(image)
        if img is None or not self._templates:
            return 0.0
        return self._emblem_score(img, cx, cy)

    def detect_panel(self, image) -> Detection | None:
        """Raw panel-pill candidate by emblem score at the fixed spot. NOTE: a
        bare score here is not evidence the province-detail panel is *open* — the
        scan corroborates it before reporting a panel (see build_scan)."""
        img = self._as_image(image)
        if img is None or not self._templates:
            return None
        px, py = PANEL_PILL_CENTER
        score = self._emblem_score(img, px - self._offset[0], py - self._offset[1])
        if score < self._threshold:
            return None
        return self._make(px - self._offset[0], py - self._offset[1], score, "panel")

    # --- stage 1: locate ----------------------------------------------------

    def _arrow_candidates(self, img, region: tuple[int, int, int, int] | None = None) -> list[tuple[int, int, int]]:
        x0, y0, x1, y1 = self._clamped_region(img, region)
        roi = img[y0:y1, x0:x1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        red = (((hue <= 12) | (hue >= 168)) & (sat >= self._sat_min) & (val >= self._val_min))
        red = red.astype("uint8")
        red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((2, 2), "uint8"))
        count, _lbl, stats, cent = cv2.connectedComponentsWithStats(red, connectivity=8)
        out = []
        for i in range(1, count):
            area = int(stats[i, cv2.CC_STAT_AREA])
            bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
            if not (self._min_area <= area <= self._max_area) or bw > self._max_side or bh > self._max_side:
                continue
            out.append((int(cent[i][0]) + x0, int(cent[i][1]) + y0, area))
        return out

    # --- stage 2: confirm ---------------------------------------------------

    def _emblem_score(self, img, arrow_cx: int, arrow_cy: int) -> float:
        """Best multi-scale, masked template score in a small window around the
        arrow — the confidence a real emblem sits here."""
        best = 0.0
        for s in self._scales:
            w = h = int(round(TEMPLATE_SIZE * s))
            pad = 6
            x0 = max(0, arrow_cx - w // 2 - pad)
            y0 = max(0, arrow_cy - h // 2 - pad)
            x1 = min(img.shape[1], arrow_cx + w // 2 + pad)
            y1 = min(img.shape[0], arrow_cy + h // 2 + pad)
            window = img[y0:y1, x0:x1]
            if window.shape[0] < h or window.shape[1] < w:
                continue
            for tpl, mask in self._templates:
                t = cv2.resize(tpl, (w, h))
                m = cv2.resize(mask, (w, h))
                res = cv2.matchTemplate(window, t, cv2.TM_CCOEFF_NORMED, mask=m)
                res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
                v = float(res.max())
                if v > best:
                    best = v
        return best

    def _make(self, arrow_cx: int, arrow_cy: int, score: float, kind: str) -> Detection:
        ox, oy = self._offset
        cx, cy = arrow_cx + ox, arrow_cy + oy
        s = TEMPLATE_SIZE
        return Detection(
            cx=cx, cy=cy, x=cx - s // 2, y=cy - s // 2, w=s, h=s,
            confidence=min(1.0, max(0.0, score)), kind=kind,
        )

    def _nms(self, detections: list[Detection]) -> list[Detection]:
        kept: list[Detection] = []
        r2 = self._nms_radius * self._nms_radius
        for det in sorted(detections, key=lambda d: -d.confidence):
            if all((det.cx - k.cx) ** 2 + (det.cy - k.cy) ** 2 > r2 for k in kept):
                kept.append(det)
        return kept

    # --- helpers ------------------------------------------------------------

    def _clamped_region(self, img, region: tuple[int, int, int, int] | None = None):
        h, w = img.shape[:2]
        x0, y0, x1, y1 = region if region is not None else self._region
        x0, y0 = max(0, min(x0, w)), max(0, min(y0, h))
        x1, y1 = max(x0, min(x1, w)), max(y0, min(y1, h))
        return x0, y0, x1, y1

    def _as_image(self, image):
        if isinstance(image, (str, Path)):
            return cv2.imread(str(image))
        return image


__all__ = [
    "BadgeDetector", "Detection", "DetectResult", "DEFAULT_REGION", "PANEL_PILL_CENTER",
    "TEMPLATE_SIZE", "load_bundled_templates",
]
