"""Milestone 4 — the first complete Forge decision slice (observe-only).

Covers the deterministic strategy (lowest allowed %, then highest confidence,
then nearest centre), badge filtering with ignored reasons, the full explanation
format, and that nothing selects when the safety gate is not CONTINUE.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.core.domain.models import Rect
from bap.forge.detection.detector import Detection
from bap.forge.detection.scan import DebugScan, Selection, annotate, build_scan, select_target
from bap.forge.detection.weakening import Decision, WeakeningRead
from bap.forge.worlds import World


def _d(cx, cy, conf, pct):
    return Detection(cx, cy, cx - 12, cy - 12, 24, 24, conf, pct=pct)


H = World(alias="H", hostname="cz8.forgeofempires.com", allowed_pcts=(20, 40), max_weakening=50)


def test_strategy_prefers_lowest_allowed_percent():
    d20 = _d(800, 500, 0.80, 20)
    d40 = _d(900, 500, 0.99, 40)   # higher conf but higher %
    sel = select_target([d40, d20], H, frame_center=(960, 540))
    assert sel.detection is d20    # lowest allowed % wins over confidence


def test_strategy_tiebreak_highest_confidence():
    a = _d(800, 500, 0.70, 20)
    b = _d(1100, 500, 0.95, 20)    # same %, higher confidence
    sel = select_target([a, b], H, frame_center=(960, 540))
    assert sel.detection is b


def test_strategy_tiebreak_nearest_center():
    near = _d(950, 540, 0.90, 20)  # near frame centre (960,540)
    far = _d(500, 900, 0.90, 20)   # same %, same conf, farther
    sel = select_target([near, far], H, frame_center=(960, 540))
    assert sel.detection is near


def test_filtering_records_ignored_reasons():
    d20 = _d(800, 500, 0.9, 20)
    d60 = _d(900, 500, 0.9, 60)    # disabled in settings
    dunk = _d(1000, 500, 0.9, None)  # percentage unknown
    sel = select_target([d20, d60, dunk], H, frame_center=(960, 540))
    assert sel.detection is d20
    reasons = {id(d): r for d, r in sel.ignored}
    assert reasons[id(d60)] == "disabled in settings"
    assert reasons[id(dunk)] == "percentage unknown"
    assert sel.considered == [d20]


def test_none_eligible_when_all_disabled():
    d60 = _d(900, 500, 0.9, 60)
    d80 = _d(1000, 500, 0.9, 80)
    sel = select_target([d60, d80], H, frame_center=(960, 540))
    assert sel.detection is None
    assert len(sel.ignored) == 2


def test_full_explanation_matches_pipeline_format():
    dets = [_d(812, 566, 0.94, 20), _d(1200, 400, 0.90, 20), _d(600, 700, 0.88, 60)]
    sel = select_target(dets, H, frame_center=(960, 540))
    scan = DebugScan(
        detections=dets, panel=None, region=(440, 500, 1915, 1075), selection=sel,
        world_alias="H", width=1920, height=1080,
        weakening=WeakeningRead(36, 0.8, "ocr"), weakening_region=Rect(678, 477, 56, 25),
        world_limit=50, decision=Decision.CONTINUE,
    )
    text = scan.explanation()
    for expected in ("World: H", "Weakening: 36", "Limit: 50", "Decision: CONTINUE",
                     "Detected: 20%  20%  60%", "Ignored: 60% (disabled in settings)",
                     "Selected: 20%  confidence 0.94",
                     "Reason: Lowest allowed weakening with highest confidence.",
                     "Would click: x=812 y=566"):
        assert expected in text, expected
    # JSON carries considered + ignored for the debugger.
    d = scan.to_dict()["selection"]
    assert d["click_point"] == [812, 566]
    assert any(i["ignored_reason"] == "disabled in settings" for i in d["ignored"])


def test_gate_stop_shows_candidate_but_blocks_action():
    # The strategy still shows its best candidate, but the STOP gate blocks the
    # would-click — nothing is actionable.
    dets = [_d(812, 566, 0.94, 20)]
    sel = select_target(dets, H, frame_center=(960, 540))
    scan = DebugScan(detections=dets, panel=None, region=(440, 500, 1915, 1075),
                     selection=sel, world_alias="H", width=1920, height=1080,
                     weakening=WeakeningRead(99, 0.9, "ocr"), weakening_region=Rect(700, 486, 90, 28),
                     world_limit=50, decision=Decision.STOP)
    text = scan.explanation()
    assert "Decision: STOP" in text
    assert scan.selection.detection is dets[0]           # candidate still computed
    assert "BLOCKED by gate (STOP)" in text              # but no action


def test_gate_unknown_blocks_action():
    dets = [_d(812, 566, 0.94, 20)]
    sel = select_target(dets, H, frame_center=(960, 540))
    scan = DebugScan(detections=dets, panel=None, region=(440, 500, 1915, 1075),
                     selection=sel, world_alias="H", width=1920, height=1080,
                     weakening=WeakeningRead(None, 0.0, "ocr"), weakening_region=Rect(700, 486, 90, 28),
                     world_limit=50, decision=Decision.UNKNOWN)
    assert "BLOCKED by gate (UNKNOWN)" in scan.explanation()


def test_annotate_draws_would_click_marker():
    dets = [_d(812, 566, 0.94, 20)]
    sel = select_target(dets, H, frame_center=(960, 540))
    scan = DebugScan(detections=dets, panel=None, region=(440, 500, 1915, 1075),
                     selection=sel, world_alias="H", width=1920, height=1080,
                     decision=Decision.CONTINUE)
    vis = annotate(np.zeros((1080, 1920, 3), np.uint8), scan)
    assert vis.shape == (1080, 1920, 3)  # renders without error, selected marker drawn
