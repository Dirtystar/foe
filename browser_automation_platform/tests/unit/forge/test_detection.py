import json

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.forge.detection.classify import PercentClassifier, percent_patch
from bap.forge.detection.detector import (
    BadgeDetector,
    Detection,
    load_bundled_templates,
)
from bap.forge.detection.scan import annotate, build_scan, save_scan, select_target
from bap.forge.detection.evaluate import evaluate
from bap.forge.worlds import World


def _bundled():
    tpls = load_bundled_templates()
    assert tpls, "expected bundled emblem templates in assets/emblems"
    return tpls


def _frame_with_emblem(cx, cy):
    """Blank game frame with a real emblem template pasted at arrow-centre (cx,cy)."""
    img = np.zeros((1080, 1920, 3), np.uint8)
    tpl = _bundled()[0][0]
    h, w = tpl.shape[:2]
    img[cy - h // 2:cy - h // 2 + h, cx - w // 2:cx - w // 2 + w] = tpl
    return img, tpl


# --- detector -----------------------------------------------------------------


def test_detects_planted_emblem_with_offset():
    arrow_cx, arrow_cy = 900, 740
    img, _ = _frame_with_emblem(arrow_cx, arrow_cy)
    det = BadgeDetector()
    hits = det.detect(img)
    assert len(hits) == 1
    # Reported centre is arrow + the fitted (+16,0) offset.
    assert abs(hits[0].cx - (arrow_cx + 16)) <= 4
    assert abs(hits[0].cy - arrow_cy) <= 4
    assert hits[0].confidence > 0.7
    assert hits[0].kind == "map"


def test_blank_frame_no_detections():
    assert BadgeDetector().detect(np.zeros((1080, 1920, 3), np.uint8)) == []


def test_panel_pill_reported_separately_not_as_map():
    from bap.forge.detection.detector import PANEL_PILL_CENTER

    px, py = PANEL_PILL_CENTER
    img, _ = _frame_with_emblem(px - 16, py)  # emblem at the panel pill arrow spot
    det = BadgeDetector()
    assert det.detect(img) == []          # excluded from map detections
    panel = det.detect_panel(img)
    assert panel is not None and panel.kind == "panel"


def test_nms_dedupes_close_detections():
    det = BadgeDetector(nms_radius=30)
    a = Detection(100, 100, 90, 90, 20, 20, 0.9)
    b = Detection(110, 105, 100, 95, 20, 20, 0.8)  # within radius
    c = Detection(400, 400, 390, 390, 20, 20, 0.7)
    kept = det._nms([a, b, c])
    assert len(kept) == 2 and kept[0].confidence == 0.9


# --- classifier ---------------------------------------------------------------


def test_percent_classifier_nearest_neighbour():
    p20 = np.zeros(24 * 40, np.float32); p20[0] = 1.0
    p60 = np.zeros(24 * 40, np.float32); p60[-1] = 1.0
    clf = PercentClassifier().fit([(p20, 20), (p60, 60)])
    near20 = p20 + np.random.RandomState(0).normal(0, 0.01, p20.shape).astype("float32")
    near20 /= np.linalg.norm(near20)
    guess, sim = clf.predict(near20)
    assert guess == 20 and sim > 0.9


def test_empty_classifier_returns_none():
    assert PercentClassifier().predict(np.ones(10, np.float32)) == (None, 0.0)


def test_percent_patch_out_of_bounds_is_none():
    img = np.zeros((1080, 1920, 3), np.uint8)
    assert percent_patch(img, 5, 5) is None  # patch would fall off the left edge


# --- scan / debugger core -----------------------------------------------------


def test_build_scan_and_explanation():
    img, _ = _frame_with_emblem(900, 740)
    scan = build_scan(img)
    assert len(scan.detections) == 1
    text = scan.explanation()
    assert "OBSERVE ONLY — NO CLICK PERFORMED" in text
    assert scan.to_dict()["observe_only"] is True


def test_select_target_respects_world_rules():
    d20 = Detection(100, 100, 90, 90, 20, 20, 0.9, pct=20)
    d80 = Detection(200, 200, 190, 190, 20, 20, 0.9, pct=80)
    world = World(alias="H", hostname="cz8.forgeofempires.com", allowed_pcts=(20, 40), max_weakening_pct=60)
    sel = select_target([d20, d80], world)
    assert sel.detection is d20  # 80 not allowed / above max
    # none eligible
    world2 = World(alias="X", hostname="cz1.forgeofempires.com", allowed_pcts=(100,), max_weakening_pct=100)
    assert select_target([d20, d80], world2).detection is None


def test_select_target_no_classifier_declines():
    d = Detection(100, 100, 90, 90, 20, 20, 0.9, pct=None)
    sel = select_target([d], None)
    assert sel.detection is None
    assert any("not available" in r for r in sel.reasons)


def test_annotate_and_save(tmp_path):
    img, _ = _frame_with_emblem(900, 740)
    scan = build_scan(img)
    vis = annotate(img, scan)
    assert vis.shape == img.shape
    paths = save_scan(img, scan, tmp_path)
    for key in ("original", "annotated", "detections", "calibration"):
        assert (tmp_path / f"scan_{key}.png").exists() or (tmp_path / f"scan_{key}.json").exists()
    data = json.loads((tmp_path / "scan_detections.json").read_text())
    assert data["observe_only"] is True


# --- harness ------------------------------------------------------------------


def test_evaluate_reports_no_reviewed(tmp_path):
    (tmp_path / "frames").mkdir()
    cv2.imwrite(str(tmp_path / "frames" / "a.png"), np.zeros((1080, 1920, 3), np.uint8))
    (tmp_path / "labels.json").write_text(json.dumps(
        {"version": 1, "frames": [{"file": "a.png", "badges": [], "reviewed": False}]}))
    rep = evaluate(BadgeDetector(), tmp_path / "frames", tmp_path / "labels.json")
    assert rep.n_reviewed == 0
    assert "No reviewed frames" in rep.format()


def test_evaluate_matches_planted_badge(tmp_path):
    (tmp_path / "frames").mkdir()
    img, _ = _frame_with_emblem(900, 740)
    cv2.imwrite(str(tmp_path / "frames" / "a.png"), img)
    truth_cx = 900 + 16  # where the detector will report the centre
    (tmp_path / "labels.json").write_text(json.dumps({"version": 1, "frames": [
        {"file": "a.png", "badges": [{"cx": truth_cx, "cy": 740, "pct": 20}], "reviewed": True}]}))
    rep = evaluate(BadgeDetector(), tmp_path / "frames", tmp_path / "labels.json")
    assert rep.tp == 1 and rep.truth_badges == 1
    assert rep.recall == 1.0
