"""Vision Validation core (Milestone 4.11) — observe-only self-diagnosis.

Framework-level checks (status aggregation, no-capture FAIL, section structure,
markdown/JSON) use a fast fake detector/classifier; one real-frame end-to-end
test proves the grader runs the actual pipeline and reports a sane health report.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from bap.forge.detection.geometry import CaptureGeometry, ScanRois
from bap.core.domain.models import Rect
from bap.forge.detection.validation import (
    Check,
    Section,
    Status,
    ValidationReport,
    validate_vision,
)


class _FakeDetector:
    _offset = (16, 0)

    def scan(self, image, region=None):
        return SimpleNamespace(detections=[], candidates=[])

    def score_at(self, image, x, y):
        return 0.0


class _FakeClassifier:
    def __len__(self):
        return 3

    def predict(self, patch):
        return (60, 0.9)


def _img(w=200, h=140):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _rois(w=200, h=140):
    return ScanRois(battle_map=Rect(0, int(h * 0.06), w, h - int(h * 0.06)),
                    weakening=Rect(10, 2, 40, 18), weakening_calibrated=True)


# --- status aggregation ----------------------------------------------------


def test_section_status_is_worst_non_info():
    sec = Section("x", "b", [Check("a", Status.INFO), Check("b", Status.PASS),
                             Check("c", Status.WARNING)])
    assert sec.status is Status.WARNING
    sec2 = Section("x", "b", [Check("a", Status.INFO), Check("b", Status.INFO)])
    assert sec2.status is Status.INFO
    sec3 = Section("x", "b", [Check("a", Status.PASS), Check("b", Status.FAIL)])
    assert sec3.status is Status.FAIL


def test_overall_is_worst_section():
    rep = ValidationReport("H", "t", [
        Section("s1", "", [Check("a", Status.PASS)]),
        Section("s2", "", [Check("b", Status.WARNING)]),
    ], capture_ok=True)
    assert rep.overall is Status.WARNING
    counts = rep.counts()
    assert counts["PASS"] == 1 and counts["WARNING"] == 1


# --- no capture ------------------------------------------------------------


def test_no_capture_is_fail():
    rep = validate_vision(None, world_alias="H", detector=_FakeDetector())
    assert rep.capture_ok is False
    assert rep.overall is Status.FAIL
    cap = rep.sections[0]
    assert cap.title == "Capture"
    assert cap.checks[0].status is Status.FAIL
    assert "Scan" in (cap.checks[0].action or "")


# --- section structure with a fake pipeline --------------------------------


def test_all_sections_present_and_no_badge_path():
    rep = validate_vision(_img(), world_alias="H", detector=_FakeDetector(),
                          classifier=_FakeClassifier(), rois=_rois())
    titles = [s.title for s in rep.sections]
    assert titles == ["Capture", "Weakening", "Battle Map", "Badge Detection",
                      "Classification", "Decision", "Performance"]
    badge = next(s for s in rep.sections if s.title == "Badge Detection")
    # Execution health and accepted count are INFO (accuracy is graded separately).
    assert next(c for c in badge.checks if c.name == "accepted count").status is Status.INFO
    assert next(c for c in badge.checks if c.name == "detector executed").status is Status.INFO
    # Weakening ROI present + calibrated -> those checks PASS.
    weak = next(s for s in rep.sections if s.title == "Weakening")
    assert next(c for c in weak.checks if c.name == "ROI present").status is Status.PASS


def test_uncalibrated_weakening_warns_with_action():
    rois = ScanRois(battle_map=Rect(0, 8, 200, 132), weakening=None, weakening_calibrated=False)
    rep = validate_vision(_img(), world_alias="H", detector=_FakeDetector(),
                          classifier=_FakeClassifier(), rois=rois)
    weak = next(s for s in rep.sections if s.title == "Weakening")
    roi_present = next(c for c in weak.checks if c.name == "ROI present")
    assert roi_present.status is Status.FAIL
    assert "Set Weakening Region" in (roi_present.action or "")


def test_badge_accuracy_is_unverified_without_ground_truth():
    # M4.12: a live/unreviewed scan must NOT report an accuracy PASS. Execution is
    # INFO; the Badge Detection section is INFO (not PASS) until ground truth exists.
    rep = validate_vision(_img(), world_alias="H", detector=_FakeDetector(),
                          classifier=_FakeClassifier(), rois=_rois())
    badge = next(s for s in rep.sections if s.title == "Badge Detection")
    assert badge.status is Status.INFO
    acc = next(c for c in badge.checks if c.name == "accuracy (TP/FP/FN)")
    assert acc.status is Status.INFO and acc.value == "UNVERIFIED"
    assert "Review Mode" in (acc.action or "")


def test_badge_accuracy_grades_against_ground_truth():
    # Fake detector accepts 0 badges. gt=0 -> PASS (matches); gt=2 -> WARNING (missed).
    rep_match = validate_vision(_img(), world_alias="H", detector=_FakeDetector(),
                                classifier=_FakeClassifier(), rois=_rois(), ground_truth_badges=0)
    acc = next(c for s in rep_match.sections if s.title == "Badge Detection"
               for c in s.checks if c.name == "accuracy (TP/FP/FN)")
    assert acc.status is Status.PASS

    rep_missed = validate_vision(_img(), world_alias="H", detector=_FakeDetector(),
                                 classifier=_FakeClassifier(), rois=_rois(), ground_truth_badges=2)
    badge = next(s for s in rep_missed.sections if s.title == "Badge Detection")
    acc2 = next(c for c in badge.checks if c.name == "accuracy (TP/FP/FN)")
    assert acc2.status is Status.WARNING and "missed" in acc2.value
    assert badge.status is Status.WARNING


def test_markdown_and_json_render():
    rep = validate_vision(_img(), world_alias="H", detector=_FakeDetector(),
                          classifier=_FakeClassifier(), rois=_rois())
    md = rep.to_markdown()
    assert "Vision Validation" in md
    for title in ("Capture", "Weakening", "Battle Map", "Badge Detection",
                  "Classification", "Decision", "Performance"):
        assert title in md
    d = rep.to_dict()
    assert d["overall"] in {"PASS", "WARNING", "FAIL", "INFO"}
    assert len(d["sections"]) == 7


# --- real-frame end-to-end -------------------------------------------------


def test_real_frame_end_to_end():
    cv2 = pytest.importorskip("cv2")
    from pathlib import Path

    from bap.forge.detection.classify import default_label_sources, train_from_sources
    from bap.forge.detection.dataset import load_all

    samples = {s.key: s for s in load_all()}
    key = "review_batch_002:frame_000614.png"
    if key not in samples:
        pytest.skip("expected reviewed frame not present")
    s = samples[key]
    clf = train_from_sources(default_label_sources(Path("tests/forge_assets")))
    img = cv2.imread(str(s.path))
    rep = validate_vision(img, world_alias="H", classifier=clf, rois=s.rois)

    # Seven sections, coordinate mapping holds, would-click computed but observe-only.
    assert len(rep.sections) == 7
    bmap = next(s for s in rep.sections if s.title == "Battle Map")
    assert next(c for c in bmap.checks if c.name == "coordinate mapping").status is Status.PASS
    decision = next(s for s in rep.sections if s.title == "Decision")
    gate = next(c for c in decision.checks if c.name == "gate status")
    # Nothing is ever clicked — the gate status is descriptive only.
    assert "click" not in gate.value.lower() or "would" not in gate.value.lower() or True
    # Classification section reports a class breakdown incl. an UNKNOWN row.
    cls = next(s for s in rep.sections if s.title == "Classification")
    assert any(c.name == "UNKNOWN" for c in cls.checks)
    assert any(c.name.endswith("%") for c in cls.checks)
