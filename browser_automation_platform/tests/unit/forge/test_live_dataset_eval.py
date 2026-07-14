"""Unified dataset loader + live-set regression (observe-only).

Locks the M4.7 outcome: with the reviewed live data, the detector at threshold
0.62 finds every live badge with zero false positives, and the whole slice
produces zero wrong-accepted percentages on the live set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

import json

from bap.forge.detection.dataset import (
    HISTORICAL_DIR,
    LIVE_DIR,
    load_all,
    load_historical,
    load_live,
    load_review_batch,
)
from bap.forge.detection.detector import BadgeDetector
from bap.forge.detection.live_eval import (
    evaluate_classification,
    evaluate_full_slice,
    evaluate_localization,
)

_HAVE_LIVE = (Path(LIVE_DIR) / "labels.json").exists()
_HAVE_HIST = (Path(HISTORICAL_DIR) / "labels.json").exists()
pytestmark = pytest.mark.skipif(not (_HAVE_LIVE and _HAVE_HIST), reason="datasets missing")


# --- loader contract ----------------------------------------------------------


def test_sources_are_tagged_and_disjoint():
    hist = load_historical()
    live = load_live()
    assert hist and live
    assert all(s.source == "historical" and s.world is None for s in hist)
    assert all(s.source == "live" for s in live)
    # Live World alias is parsed from the filename prefix.
    assert {s.world for s in live} == {"H", "F"}
    # No frame key collides across sources.
    keys = [s.key for s in load_all()]
    assert len(keys) == len(set(keys))


def test_samples_carry_geometry_rois_badges_weakening():
    live = load_live()
    by_world = {}
    for s in live:
        by_world.setdefault(s.world, s)
    h = by_world["H"]
    assert (h.width, h.height) == (1920, 912)
    # Weakening ROI is in the top bar (small y); battle-map ROI covers the map.
    assert h.rois.weakening is not None and h.rois.weakening.y < 60
    assert h.rois.battle_map.w > 1000
    assert h.weakening == 592
    assert any(b.pct == 20 for b in h.badges) and any(b.pct == 60 for b in h.badges)


def test_review_batch_absent_is_clean_skip():
    # review_batch_002 is not committed yet; the loader must skip it, not error,
    # and load_all must still return only the present sources.
    assert load_review_batch() == []
    sources = {s.source for s in load_all()}
    assert sources <= {"historical", "live", "review_batch_002"}
    assert "review_batch_002" not in sources     # absent today


def test_review_batch_included_when_present(tmp_path):
    # A synthetic batch root is picked up by load_review_batch and tagged.
    frames = tmp_path / "frames"
    frames.mkdir()
    cv2.imwrite(str(frames / "H_x.png"), np.full((80, 120, 3), 40, np.uint8))
    (tmp_path / "labels.json").write_text(json.dumps({"version": 1, "frames": [
        {"file": "H_x.png", "badges": [{"cx": 30, "cy": 30, "pct": 20}], "reviewed": True}]}))
    from bap.core.domain.models import Rect
    from bap.forge.detection.calibration import WeakeningCalibration
    WeakeningCalibration(path=tmp_path / "calibration.json").set(120, 80, Rect(2, 2, 20, 10))
    samples = load_review_batch(tmp_path)
    assert len(samples) == 1
    assert samples[0].source == "review_batch_002" and samples[0].world == "H"
    assert samples[0].badges[0].pct == 20


def test_load_all_dedups_by_content_keeping_last(tmp_path, monkeypatch):
    # A frame that appears in two roots (same bytes) is counted once, and the
    # LATER (reviewed) source's labels win.
    import bap.forge.detection.dataset as ds
    from bap.core.domain.models import Rect
    from bap.forge.detection.calibration import WeakeningCalibration

    def make(root, pct):
        (root / "frames").mkdir(parents=True)
        # identical image bytes in both roots
        cv2.imwrite(str(root / "frames" / "dup.png"), np.full((80, 120, 3), 7, np.uint8))
        (root / "labels.json").write_text(json.dumps({"version": 1, "frames": [
            {"file": "dup.png", "badges": [{"cx": 30, "cy": 30, "pct": pct}], "reviewed": True}]}))
        WeakeningCalibration(path=root / "calibration.json").set(120, 80, Rect(2, 2, 20, 10))

    a, b, empty = tmp_path / "grading", tmp_path / "batch", tmp_path / "live"
    make(a, 20)
    make(b, 60)
    (empty / "frames").mkdir(parents=True)
    (empty / "labels.json").write_text(json.dumps({"version": 1, "frames": []}))
    # Make the two roots share identical bytes (copy a's frame into b).
    import shutil
    shutil.copy2(a / "frames" / "dup.png", b / "frames" / "dup.png")
    samples = ds.load_all(historical=a, live=empty, review_batch=b)
    # empty live -> no samples; dup collapsed to one, reviewed batch (60) wins.
    assert len(samples) == 1
    assert samples[0].badges[0].pct == 60 and samples[0].source == "review_batch_002"


# --- live-set regression (fast: 3 frames) -------------------------------------


def test_live_localization_perfect_recall_zero_false_positives():
    live = load_live()
    loc = evaluate_localization(live, BadgeDetector())  # default threshold 0.62
    combined = loc["combined"]
    assert combined.recall == 1.0            # all 6 live badges found
    assert combined.fp == 0                  # no false positives at 0.62
    assert combined.precision == 1.0


def test_live_slice_has_zero_wrong_accepted_percentages():
    live = load_live()
    sl = evaluate_full_slice(live, detector=BadgeDetector())
    for group, r in sl.items():
        assert r.wrong_accepted_pct == 0, group


def test_live_classification_never_wrong_accepted():
    # Live-H reads correctly (same-scale sibling); live-F stays UNKNOWN, never
    # wrong. The safety invariant holds regardless.
    cls = evaluate_classification(load_live())
    for group, r in cls.items():
        assert r.wrong == 0, group
    assert cls["live-H"].correct == 4        # H fully classified under LOFO
