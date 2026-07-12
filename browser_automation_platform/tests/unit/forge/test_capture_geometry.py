"""Capture geometry, ROIs, the coordinate contract, panel suppression, and
classification diagnosis — the pipeline fixes from the Windows capture-geometry
review.

`frame_000536` is the regression fixture: a full raw capture that contains the
Forge top bar (with the current weakening), the whole visible map, on-map badges,
and an open province panel. The next Windows review verifies against this shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.core.domain.models import Rect
from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.detection.classify import PercentClassifier, percent_patch, train_from_labels
from bap.forge.detection.detector import Detection
from bap.forge.detection.geometry import (
    CaptureGeometry,
    ScanRois,
    default_battle_map,
    derive_rois,
)
from bap.forge.detection.scan import (
    MIN_PCT_SIM,
    DebugScan,
    Selection,
    annotate,
    build_scan,
    save_scan,
)
from bap.forge.detection.weakening import Decision
from bap.forge.worlds import World

GRADING = Path(__file__).resolve().parents[3] / "tests" / "forge_assets" / "grading"
FIXTURE = GRADING / "frames" / "frame_000536.png"
H = World(alias="H", hostname="cz8.forgeofempires.com", allowed_pcts=(20, 40), max_weakening=50)


# --- capture geometry + ROIs --------------------------------------------------


def test_capture_geometry_key_includes_all_known_fields():
    g = CaptureGeometry(raw_w=1920, raw_h=1080, viewport_w=1600, viewport_h=900,
                        device_pixel_ratio=1.5, zoom=1.0)
    assert g.key() == "1920x1080|vp1600x900|dpr1.5|z1"
    # Raw size alone when nothing finer is known — but distinct setups still differ.
    assert CaptureGeometry(1920, 1080).key() == "1920x1080"


def test_default_battle_map_covers_whole_width_below_top_bar():
    g = CaptureGeometry(1920, 1080)
    weak = Rect(678, 477, 56, 25)
    bm = default_battle_map(g, weak)
    assert bm.x == 0 and bm.w == 1920            # full capture width
    assert bm.y == weak.y + weak.h               # starts just below the top bar
    assert bm.y + bm.h == 1080                    # down to the bottom
    # With no weakening ROI it still spans the whole width, skipping a thin band.
    bm2 = default_battle_map(g)
    assert bm2.x == 0 and bm2.w == 1920 and 0 < bm2.y < 1080


def test_derive_rois_uses_calibration_and_falls_back_for_map(tmp_path):
    cal = WeakeningCalibration(path=tmp_path / "c.json")
    cal.set(1920, 1080, Rect(678, 477, 56, 25))
    rois = derive_rois(CaptureGeometry(1920, 1080), cal)
    assert rois.weakening == Rect(678, 477, 56, 25) and rois.weakening_calibrated
    assert rois.battle_map_calibrated is False    # no map calibration → whole-map fallback
    assert rois.battle_map.x == 0 and rois.battle_map.w == 1920


def test_calibration_persists_battle_map_and_geometry(tmp_path):
    path = tmp_path / "c.json"
    cal = WeakeningCalibration(path=path)
    cal.set(1920, 1080, Rect(678, 477, 56, 25))
    cal.set_battle_map(1920, 1080, Rect(0, 502, 1920, 578))
    cal.set_geometry(CaptureGeometry(1920, 1080, viewport_w=1600, viewport_h=900))
    reloaded = WeakeningCalibration.load(path)
    assert reloaded.get(1920, 1080) == Rect(678, 477, 56, 25)
    assert reloaded.get_battle_map(1920, 1080) == Rect(0, 502, 1920, 578)
    assert reloaded.geometry_for(1920, 1080)["viewport_w"] == 1600


# --- coordinate contract ------------------------------------------------------


def _scan_with(det: Detection, roi: Rect) -> DebugScan:
    rois = ScanRois(battle_map=roi, weakening=None)
    return DebugScan(detections=[det], panel=None, region=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h),
                     selection=Selection(det, ["x"], considered=[det]), rois=rois,
                     width=1920, height=1080)


def test_coordinate_contract_offset_applied_exactly_once():
    roi = Rect(0, 502, 1920, 578)
    det = Detection(cx=945, cy=714, x=925, y=694, w=40, h=40, confidence=0.9, pct=20)
    d = _scan_with(det, roi).to_dict()["detections"][0]
    # Full-image coordinates are the detector's output as-is.
    assert d["center_full"] == [945, 714]
    assert d["bbox_full"] == [925, 694, 40, 40]
    # ROI-local box = full box minus the ROI origin, applied once (not twice).
    assert d["bbox_roi"] == [925 - roi.x, 694 - roi.y, 40, 40] == [925, 192, 40, 40]
    # Reconstructing full from roi-local + origin round-trips exactly.
    assert d["bbox_roi"][0] + roi.x == d["bbox_full"][0]
    assert d["bbox_roi"][1] + roi.y == d["bbox_full"][1]


def test_click_point_is_full_image_coordinates():
    roi = Rect(0, 502, 1920, 578)
    det = Detection(cx=945, cy=714, x=925, y=694, w=40, h=40, confidence=0.9, pct=20)
    d = _scan_with(det, roi).to_dict()["selection"]
    assert d["click_point_full"] == [945, 714]


# --- panel suppression --------------------------------------------------------


def test_no_false_panel_on_empty_terrain():
    blank = np.zeros((1080, 1920, 3), np.uint8)
    scan = build_scan(blank, world=H)
    assert scan.panel is None                      # nothing drawn
    assert scan.panel_result["present"] is False
    assert "not corroborated" in scan.panel_result["reason"] or "no panel pill" in scan.panel_result["reason"]
    vis = annotate(blank, scan)
    assert vis.shape == blank.shape                # renders, but no panel box


def test_annotate_leaves_top_bar_uncovered_no_banner():
    # The OBSERVE-ONLY banner must NOT be painted over the image — it used to
    # cover the top ~40 px where the Forge top bar (weakening) sits. A textured
    # top strip must survive annotation unchanged.
    img = np.full((1080, 1920, 3), 200, np.uint8)   # uniform bright top bar
    # No weakening ROI: the default map ROI starts ~6% down, so the top strip has
    # no annotation at all — it must be byte-identical (the old red banner would
    # have overwritten it).
    scan = build_scan(img, world=H)
    vis = annotate(img, scan)
    assert np.array_equal(vis[0:40, :, :], img[0:40, :, :])


def test_panel_state_not_in_explanation_but_in_scan_json():
    img = np.zeros((1080, 1920, 3), np.uint8)
    scan = build_scan(img, world=H)
    assert "Province panel" not in scan.explanation()   # not in the debugger text
    assert scan.to_dict()["panel"] is not None          # kept for diagnosis


# --- classification diagnosis -------------------------------------------------


def test_low_similarity_percentage_is_left_unknown_not_accepted():
    # Two exemplars; a query near one is accepted, a query near neither is not.
    p20 = np.zeros(24 * 40, np.float32); p20[0] = 1.0
    p40 = np.zeros(24 * 40, np.float32); p40[1] = 1.0
    clf = PercentClassifier().fit([(p20, 20), (p40, 40)])
    orth = np.zeros(24 * 40, np.float32); orth[500] = 1.0   # cosine ~0 to both
    guess, sim = clf.predict(orth)
    assert sim < MIN_PCT_SIM                        # below the acceptance bar
    # The scan must record it as UNKNOWN with a reason, never silently valid.
    from bap.forge.detection.scan import _classify
    det = Detection(cx=945, cy=714, x=925, y=694, w=40, h=40, confidence=0.9)

    class _Fixed:
        def __len__(self): return 2
        def predict(self, _patch): return 20, 0.30   # a match, but low similarity

    img = np.random.RandomState(0).randint(0, 255, (1080, 1920, 3), np.uint8)  # textured crop
    out, diag = _classify(img, [det], _Fixed())
    assert out[0].pct is None                       # not accepted
    assert diag[0]["accepted"] is False and "UNKNOWN" in diag[0]["reason"]


# --- regression fixture (real full capture) -----------------------------------


@pytest.mark.skipif(not FIXTURE.exists(), reason="grading fixture frame missing")
def test_regression_full_capture_pipeline(tmp_path):
    img = cv2.imread(str(FIXTURE))
    cal = WeakeningCalibration.load(GRADING / "calibration.json")
    clf = train_from_labels(GRADING / "frames", GRADING / "labels.json")
    geo = CaptureGeometry.from_image(img)
    rois = derive_rois(geo, cal)

    # Acceptance: the raw capture contains the top bar (weakening ROI) ABOVE the
    # battle-map ROI, and the map ROI spans the whole width.
    assert rois.weakening is not None
    assert rois.weakening.y + rois.weakening.h <= rois.battle_map.y
    assert rois.battle_map.x == 0 and rois.battle_map.w == img.shape[1]

    scan = build_scan(img, world=H, classifier=clf, rois=rois, geometry=geo)

    # The weakening gate read the top-bar value (outside the map ROI) and decided.
    assert scan.weakening is not None and scan.weakening.value is not None
    assert scan.decision in (Decision.CONTINUE, Decision.STOP, Decision.UNKNOWN)

    # Badges are located inside the battle-map ROI, and their reported centres are
    # full-image coordinates.
    assert scan.detections
    bm = scan.battle_map_roi
    for d in scan.detections:
        assert bm.x <= d.cx <= bm.x + bm.w and bm.y <= d.cy <= bm.y + bm.h

    # The high-confidence 40% badge classifies; every accepted pct is a valid
    # class, and none is a wrong value (at MIN_PCT_SIM 0.62 a marginal read stays
    # UNKNOWN rather than being accepted wrongly).
    pcts = {d.pct for d in scan.detections if d.pct is not None}
    assert 40 in pcts
    assert pcts <= {20, 40, 60, 80, 100}
    # Every candidate has a classification diagnostic (predicted / similarity / reason).
    assert len(scan.classify_diag) == len(scan.detections)
    assert all("reason" in c for c in scan.classify_diag)

    # No false province-panel box.
    assert scan.panel is None

    # The full artifact set is written for review.
    save_scan(img, scan, tmp_path)
    for name in ("01_full_raw_capture.png", "02_weakening_roi_raw.png",
                 "03_weakening_roi_processed.png", "04_battle_map_roi_raw.png",
                 "05_badge_candidate_overlay.png", "06_badge_classifier_crops",
                 "07_final_annotated_output.png", "scan.json"):
        assert (tmp_path / name).exists(), name

    # The saved full raw capture is the unmodified input — no banner/boxes baked in.
    raw = cv2.imread(str(tmp_path / "01_full_raw_capture.png"))
    assert np.array_equal(raw, img)


@pytest.mark.skipif(not FIXTURE.exists(), reason="grading fixture frame missing")
def test_contact_sheet_and_per_candidate_crops(tmp_path):
    img = cv2.imread(str(FIXTURE))
    cal = WeakeningCalibration.load(GRADING / "calibration.json")
    clf = train_from_labels(GRADING / "frames", GRADING / "labels.json")
    scan = build_scan(img, world=H, classifier=clf,
                      rois=derive_rois(CaptureGeometry.from_image(img), cal))
    save_scan(img, scan, tmp_path, classifier=clf)
    # Contact sheet (live vs nearest exemplars) + per-candidate emblem/percent crops.
    assert (tmp_path / "08_classifier_contact_sheet.png").exists()
    crops = tmp_path / "06_badge_classifier_crops"
    assert (crops / "cand00_emblem.png").exists()
    assert (crops / "cand00_percent.png").exists()
    assert (crops / "cand00_classifier_input.png").exists()


def test_classifier_nearest_returns_labelled_images():
    p20 = np.zeros(24 * 40, np.float32); p20[0] = 1.0
    p40 = np.zeros(24 * 40, np.float32); p40[1] = 1.0
    clf = PercentClassifier().fit([(p20, 20), (p40, 40)])
    nearest = clf.nearest(p20, 5)
    assert nearest[0][0] == 20 and nearest[0][1] > 0.9       # best is 20% pill
    assert nearest[0][2].shape == (24, 40)                   # rendered exemplar image
