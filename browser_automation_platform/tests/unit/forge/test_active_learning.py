"""Active-learning review-batch selector (observe-only, no retrain).

Covers near-duplicate clustering, diversity-capped selection (NOT top-N by
score), and a Review-Mode-ready batch folder. The models/thresholds are used
read-only — a guard test asserts the shipped thresholds are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.core.domain.models import Rect
from bap.forge.detection.active_learning import (
    FrameInfo,
    build_review_batch,
    cluster,
    select_batch,
)
from bap.forge.detection.calibration import WeakeningCalibration


def _info(name, desc, score_factor, clusterable_group=None):
    fi = FrameInfo(file=name, source_path=Path(name), source="t", world=None,
                   width=100, height=100, descriptor=desc)
    fi.factors = {"unknown_pct": score_factor}
    return fi


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def test_cluster_merges_near_duplicates_only():
    a = _unit([1, 0, 0, 0])
    a2 = _unit([1, 0.01, 0, 0])   # ~identical to a
    b = _unit([0, 1, 0, 0])       # distinct
    infos = [_info("a", a, 1), _info("a2", a2, 1), _info("b", b, 1)]
    n = cluster(infos)
    assert n == 2                                  # a & a2 merge, b separate
    assert infos[0].cluster == infos[1].cluster
    assert infos[2].cluster != infos[0].cluster


def test_selection_is_diversity_capped_not_top_n():
    # One cluster holds the 4 highest-scoring frames; a top-N-by-score selector
    # would take all of them. Diversity capping must instead spread across clusters.
    dupe = _unit([1, 0, 0])
    distinct = [_unit([0, 1, 0]), _unit([0, 0, 1]), _unit([1, 1, 1])]
    infos = [_info(f"dupe{i}", _unit([1, 0.001 * i, 0]), 100 - i) for i in range(4)]
    for j, d in enumerate(distinct):
        infos.append(_info(f"other{j}", d, 10 + j))
    cluster(infos)
    picked = select_batch(infos, n=4)
    from collections import Counter
    per_cluster = Counter(f.cluster for f in picked)
    # The 4-strong duplicate cluster must NOT supply all 4 picks.
    assert max(per_cluster.values()) < 4
    assert len({f.cluster for f in picked}) >= 2   # spread across clusters


def _tiny_frame(path, color):
    img = np.full((120, 160, 3), color, np.uint8)
    cv2.imwrite(str(path), img)


def test_build_review_batch_is_review_mode_ready(tmp_path):
    frames = tmp_path / "src"
    frames.mkdir()
    for i, col in enumerate([(30, 60, 90), (90, 60, 30), (10, 120, 10)]):
        _tiny_frame(frames / f"f{i}.png", col)
    cal = WeakeningCalibration(path=tmp_path / "calibration.json")
    cal.set(160, 120, Rect(2, 2, 20, 10))
    out = tmp_path / "batch"
    manifest = build_review_batch([(frames, tmp_path / "calibration.json", "t")], out, n=50)

    # Structure.
    assert (out / "manifest.json").exists() and (out / "REVIEW_BATCH.md").exists()
    assert (out / "labels.json").exists() and (out / "calibration.json").exists()
    assert len(list((out / "frames").glob("*.png"))) == 3
    assert manifest["selected"] == 3 and manifest["corpus_frames"] == 3
    assert manifest["note"]                          # honest small-corpus note
    for row in manifest["frames"]:
        assert row["reasons"]                        # every frame explains WHY
        assert "detector" in row and "factors" in row

    # Directly openable by the existing Review Mode label session (unreviewed).
    from bap.forge.labeling.session import LabelSession
    session = LabelSession.open(out / "frames", out / "labels.json")
    assert session.total == 3
    assert session.reviewed_count() == 0


def test_thresholds_unchanged_readonly_guard():
    # Active learning must not have touched the models/thresholds.
    from bap.forge.detection.detector import BadgeDetector
    from bap.forge.detection.scan import MIN_PCT_SIM
    assert BadgeDetector()._threshold == 0.62
    assert MIN_PCT_SIM == 0.62
