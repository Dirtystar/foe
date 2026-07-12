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

from bap.forge.detection.dataset import (
    HISTORICAL_DIR,
    LIVE_DIR,
    load_all,
    load_historical,
    load_live,
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
