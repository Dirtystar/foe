"""State detectors — one per known UI state, in a registry (Milestone A, read-only).

Each detector answers only for **its own** state: given a screenshot it returns a
:class:`StateEvidence` (a score in [0, 1] + the supporting signals). It never claims
another state and never decides what to do. The classifier
(:func:`screen_state.classify_screen`) runs the registry and applies the fail-safe
decision rule.

These detectors **reuse the existing, frozen** :class:`BadgeDetector` read-only — they
add no new vision and change no detector/classifier/threshold. Adding a future state
(City, Battle, Result, …) means writing a new detector and registering it here; the
classifier does not change.

Signal grounding (measured on the 153 reviewed map frames; see the milestone report):
map frames carry several detected weakening badges and a **low** emblem score at the
fixed province-pill spot, so the two states separate cleanly with a wide margin;
anything that matches neither falls back to UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass

from bap.forge.detection.detector import PANEL_PILL_CENTER, BadgeDetector
from bap.forge.state.screen_state import ScreenState, StateEvidence, StateSignal

# The province-detail panel pill emblem clears this on a real open panel; map frames
# sit well below it (measured). Matches scan.PANEL_SCORE_MIN.
PANEL_EMBLEM_MIN = 0.55
# Reference resolution the fixed panel-pill coordinate was measured at.
_REF_W, _REF_H = 1920, 1080


@dataclass
class DetectContext:
    """Shared, reusable context for the detectors. Holds one `BadgeDetector` (built
    once) so a classification does not rebuild it. Read-only w.r.t. the detector.

    ``map_detections`` is an optional reuse hook: a caller that has **already** run
    the badge detector over the map ROI (e.g. the Vision Debugger's scan) can pass
    those detections so the map signal is derived without a second, expensive scan.
    When None, ``detect_gbg_map`` scans itself.
    """

    detector: BadgeDetector | None = None
    map_detections: list | None = None

    def get_detector(self) -> BadgeDetector:
        if self.detector is None:
            self.detector = BadgeDetector()
        return self.detector


def _battle_map_region(image):
    """The battle-map ROI for this capture (geometry-derived, resolution-robust)."""
    from bap.forge.detection.geometry import CaptureGeometry, default_battle_map

    geo = CaptureGeometry.from_image(image)
    bm = default_battle_map(geo, None)
    return (bm.x, bm.y, bm.x + bm.w, bm.y + bm.h)


def _scaled_pill_center(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return PANEL_PILL_CENTER
    px, py = PANEL_PILL_CENTER
    return (int(round(px * width / _REF_W)), int(round(py * height / _REF_H)))


def detect_gbg_map(image, context: DetectContext) -> StateEvidence:
    """Score how strongly this looks like the Guild-Battlegrounds battle map. Evidence
    = the number of weakening badges the (frozen) detector finds in the map ROI. A
    badge-less map cannot be positively confirmed from badges alone, so it scores low
    and safely reads UNKNOWN (no guessing) — which is acceptable because we only act
    on maps that have targets."""
    if context.map_detections is not None:
        badges = len(context.map_detections)     # reuse a caller's existing scan
    else:
        det = context.get_detector()
        region = _battle_map_region(image)
        badges = len(det.scan(image, region=region).detections)
    if badges >= 1:
        score = min(0.95, 0.65 + 0.06 * badges)   # 1→0.71 … 5+→0.95
    else:
        score = 0.15
    signals = [StateSignal(ScreenState.GBG_MAP, "map_badges", badges,
                           f"{badges} weakening badge(s) detected in the map ROI")]
    return StateEvidence(score, signals, f"map badges = {badges}")


def detect_province_panel(image, context: DetectContext) -> StateEvidence:
    """Score how strongly the province/detail panel is open. Evidence = the emblem
    match at the fixed panel-pill spot (scaled to the capture resolution). This is the
    same fixed-pill signal the scan uses to corroborate a panel, read-only."""
    det = context.get_detector()
    h, w = image.shape[:2]
    cx, cy = _scaled_pill_center(w, h)
    ox, oy = getattr(det, "_offset", (0, 0))
    emblem = float(det.score_at(image, cx - ox, cy - oy))
    if emblem >= PANEL_EMBLEM_MIN:
        score = 0.60 + (emblem - PANEL_EMBLEM_MIN) / (1.0 - PANEL_EMBLEM_MIN) * 0.35
        score = min(0.95, score)
    else:
        score = emblem * 0.3   # sub-threshold: weak, cannot win
    signals = [StateSignal(ScreenState.PROVINCE_PANEL, "panel_emblem_score",
                           round(emblem, 3),
                           f"emblem match {emblem:.3f} at pill {cx, cy} "
                           f"(min {PANEL_EMBLEM_MIN})")]
    return StateEvidence(score, signals, f"panel emblem = {emblem:.3f}")


#: The registry the classifier runs. Add a future state by registering its detector.
DEFAULT_DETECTORS = {
    ScreenState.GBG_MAP: detect_gbg_map,
    ScreenState.PROVINCE_PANEL: detect_province_panel,
}


__all__ = [
    "DetectContext", "detect_gbg_map", "detect_province_panel",
    "DEFAULT_DETECTORS", "PANEL_EMBLEM_MIN",
]
