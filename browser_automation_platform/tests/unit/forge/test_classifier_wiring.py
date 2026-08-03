"""Regression: the bundled classifier must actually load and classify (M4.12).

Root cause fixed here: `_bundled_classifier` resolved the dataset to a
non-existent ``src/tests/forge_assets`` (a fixed ``parents[2]`` index), so it
returned ``None``; with no classifier the whole classification stage was skipped
and every live percentage came back UNKNOWN with "nearest similarities = (none)"
and a zero-sample confidence histogram — even for 20%, which has many exemplars.

These tests pin the wiring so the bug cannot silently return: the assets root
resolves regardless of cwd, the bundled classifier is non-empty, and real
detections reach the classifier and produce per-candidate diagnostics with a
similarity — while wrong-accepted percentage stays zero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")


def test_default_assets_root_resolves():
    from bap.forge.detection.classify import default_assets_root

    root = default_assets_root()
    assert root is not None, "reviewed dataset root must be found by walk-up"
    assert (root / "grading" / "labels.json").exists()


def test_bundled_classifier_is_non_empty():
    from bap.gui.forge_debugger import _bundled_classifier

    clf = _bundled_classifier()
    assert clf is not None, "bundled classifier must not be None (the M4.12 bug)"
    assert len(clf) > 0, "bundled classifier must have reviewed exemplars"


def _frame_with_badges():
    from bap.forge.detection.dataset import load_all

    samples = {s.key: s for s in load_all()}
    # A real reviewed frame that contains 20% badges (20% has many exemplars),
    # standing in for the operator's D 3×20% frame (not present in this repo).
    key = "review_batch_002:frame_000614.png"
    if key not in samples:
        pytest.skip("expected reviewed frame not present")
    return samples[key]


def test_live_path_reaches_classifier_and_produces_diagnostics():
    from bap.forge.detection.detector import BadgeDetector
    from bap.gui.forge_debugger import _bundled_classifier
    from bap.perf.pipeline import run_tick

    s = _frame_with_badges()
    img = cv2.imread(str(s.path))
    clf = _bundled_classifier()
    assert clf is not None and len(clf) > 0

    scan, _ = run_tick(img, world=None, detector=BadgeDetector(), classifier=clf, rois=s.rois)

    # Every accepted detection must reach the classifier and produce a diagnostic.
    assert len(scan.detections) > 0, "expected the detector to accept badge candidates"
    assert len(scan.classify_diag) == len(scan.detections), \
        "every detection must produce a classifier diagnostic (not skipped)"
    # Nearest-exemplar similarity must be present (the bug reported it missing).
    sims = [d.get("similarity") for d in scan.classify_diag]
    assert all(s is not None for s in sims), "each candidate must have a similarity"
    # At least one 20% badge should classify now that same-scale exemplars load.
    assert any(d.pct == 20 for d in scan.detections), \
        "20% has exemplars — at least one should classify once the classifier loads"
    # Safety invariant: nothing wrong-accepted (we cannot assert the labels here,
    # but the accept bar must not admit a percentage below MIN_PCT_SIM).
    from bap.forge.detection.scan import MIN_PCT_SIM

    for d, diag in zip(scan.detections, scan.classify_diag):
        if d.pct is not None:
            assert diag["similarity"] >= MIN_PCT_SIM


def test_validation_classification_section_not_empty_on_real_frame():
    from bap.forge.detection.validation import validate_vision
    from bap.gui.forge_debugger import _bundled_classifier

    s = _frame_with_badges()
    img = cv2.imread(str(s.path))
    rep = validate_vision(img, world_alias="D", classifier=_bundled_classifier(), rois=s.rois)
    cls = next(sec for sec in rep.sections if sec.title == "Classification")
    values = {c.name: c.value for c in cls.checks}
    assert values["nearest exemplar similarities"] != "(none)", \
        "nearest similarities must be populated (the reported symptom)"
    # Histogram must contain at least one sample (it was all-zero when broken).
    assert any(f"]{n}" not in values["confidence histogram"] for n in ("0",)) or \
        values["confidence histogram"] != "[0.00-0.50]0 [0.50-0.70]0 [0.70-0.85]0 [0.85-1.01]0"
