"""Regression characterization of the Windows H/F detector failures (M4.5).

These lock the two known failure modes from the review — one missed real badge
and one false-positive target — plus the TP/FP score separation, so any future
threshold or colour-prior change is measured against concrete cases rather than
eyeballed. See DETECTOR_DIAGNOSIS.md. Observe-only; no thresholds changed here.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.detection.detector import BadgeDetector
from bap.forge.detection.geometry import CaptureGeometry, derive_rois
from bap.forge.labeling.model import LabelStore

GRADING = Path(__file__).resolve().parents[3] / "tests" / "forge_assets" / "grading"
pytestmark = pytest.mark.skipif(not (GRADING / "labels.json").exists(),
                                reason="grading set missing")


def _scan(name):
    img = cv2.imread(str(GRADING / "frames" / name))
    cal = WeakeningCalibration.load(GRADING / "calibration.json")
    geo = CaptureGeometry.from_image(img)
    bm = derive_rois(geo, cal).battle_map
    res = BadgeDetector().scan(img, region=(bm.x, bm.y, bm.x + bm.w, bm.y + bm.h))
    return img, res


def _near(pt, items, r=28, key=lambda d: (d.cx, d.cy)):
    return [it for it in items if (key(it)[0] - pt[0]) ** 2 + (key(it)[1] - pt[1]) ** 2 <= r * r]


def test_known_missed_badge_is_a_colorprior_miss():
    # frame_000536 has a reviewed 20% badge at (1696,525) that is NOT detected.
    # The miss is at stage 1 (colour prior): no arrow candidate is even proposed
    # there — it is inside the battle-map ROI, so ROI clipping / NMS / the
    # classifier are not the cause. Locks the known miss + its attribution.
    _img, res = _scan("frame_000536.png")
    assert _near((1696, 525), res.detections) == []          # missed
    near_candidates = _near((1696, 525), res.candidates, r=30,
                            key=lambda c: (c["cx"], c["cy"]))
    assert near_candidates == []                             # colour prior proposed nothing


def test_known_false_positive_target_on_red_features():
    # frame_000070 yields detections that match no reviewed badge — false
    # positives from red map features in the 0.55–0.72 template band.
    _img, res = _scan("frame_000070.png")
    store = LabelStore.load(GRADING / "labels.json")
    gts = [(b.cx, b.cy) for b in store.get("frame_000070.png").badges]
    fps = [d for d in res.detections
           if not any((d.cx - g[0]) ** 2 + (d.cy - g[1]) ** 2 <= 28 * 28 for g in gts)]
    assert fps, "expected at least one known false positive on this frame"
    assert any(0.55 <= d.confidence <= 0.72 for d in fps)   # clears the 0.55 bar


def test_true_badges_score_well_above_the_false_positive_median():
    # The justification datum for any threshold decision: real badges score high
    # (min ~0.64) while false positives cluster near the bar. A detector change
    # that destroys this separation should fail here.
    store = LabelStore.load(GRADING / "labels.json")
    cal = WeakeningCalibration.load(GRADING / "calibration.json")
    det = BadgeDetector()
    tp, fp = [], []
    for name in store.files():
        fl = store.get(name)
        if fl is None or not fl.reviewed:
            continue
        img = cv2.imread(str(GRADING / "frames" / name))
        bm = derive_rois(CaptureGeometry.from_image(img), cal).battle_map
        res = det.scan(img, region=(bm.x, bm.y, bm.x + bm.w, bm.y + bm.h))
        gts = [(b.cx, b.cy) for b in fl.badges]
        for d in res.detections:
            hit = any((d.cx - g[0]) ** 2 + (d.cy - g[1]) ** 2 <= 28 * 28 for g in gts)
            (tp if hit else fp).append(d.confidence)
    assert tp and fp
    assert min(tp) >= 0.60                       # real badges score high
    assert statistics.median(fp) <= 0.66         # FPs cluster just above the bar
    assert min(tp) > statistics.median(fp)       # separable — a reviewed threshold call
