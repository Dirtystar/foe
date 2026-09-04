"""Drift guard: the timed harness must equal the real `build_scan` (Milestone 4.9).

The whole point of the harness is to time the *production* pipeline, not a copy of
it. This runs one reviewed frame through both and asserts the observable results
match exactly. It uses a single frame because the real detector is heavy (~seconds
per tick); the framework-level tests use fakes and stay fast.
"""

from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2")

from bap.forge.detection.classify import default_label_sources, train_from_sources
from bap.forge.detection.dataset import load_all
from bap.forge.detection.detector import BadgeDetector
from bap.forge.detection.scan import build_scan
from bap.perf.pipeline import run_tick


def _first_sample():
    samples = sorted(load_all(), key=lambda s: s.key)
    if not samples:
        pytest.skip("no reviewed frames available")
    return samples[0]


def test_harness_matches_build_scan_on_a_real_frame():
    from pathlib import Path

    sample = _first_sample()
    root = Path("tests/forge_assets")
    clf = train_from_sources(default_label_sources(root))
    det = BadgeDetector()
    img = cv2.imread(str(sample.path))

    ref = build_scan(img, detector=det, classifier=clf, rois=sample.rois)
    got, timer = run_tick(img, detector=det, classifier=clf, rois=sample.rois)

    assert len(got.detections) == len(ref.detections)
    assert got.decision == ref.decision
    assert got.selection.click_point == ref.selection.click_point
    assert [d.pct for d in got.detections] == [d.pct for d in ref.detections]
    got_weak = got.weakening.value if got.weakening else None
    ref_weak = ref.weakening.value if ref.weakening else None
    assert got_weak == ref_weak

    # The harness produced a per-stage breakdown for the real path.
    assert "detection" in timer.stages
    assert timer.resolved_total() > 0
