"""Milestone A — the real detectors on real data: reviewed GBG-map frames classify
as GBG_MAP (or safely UNKNOWN), are NEVER mistaken for a province panel, and a blank
frame is UNKNOWN.

Real vision (`det.scan`) is seconds per frame, so each screenshot is classified
**once** in a module-scoped fixture and every assertion reads the cached result — the
whole module runs a small, fixed number of scans.
"""

from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from bap.forge.state.detectors import DetectContext
from bap.forge.state.screen_state import (
    DEFAULT_MIN_CONFIDENCE,
    ScreenState,
    classify_screen,
)

_SAMPLE = 2   # real map frames to classify (scan is ~seconds each)
_ROOT = pathlib.Path(__file__).resolve().parents[4]   # browser_automation_platform/


@pytest.fixture(scope="module")
def classified():
    """Classify a couple of real live GBG-map frames + one blank frame ONCE."""
    paths = sorted(_ROOT.glob("dataset/frames/*.png"))
    paths += sorted(_ROOT.glob("tests/forge_assets/live_review/frames/*.png"))
    ctx = DetectContext()
    frames = []
    for p in paths:
        img = cv2.imread(str(p))
        if img is not None:
            frames.append((p.name, classify_screen(img, context=ctx)))
        if len(frames) >= _SAMPLE:
            break
    if not frames:
        pytest.skip("no reviewed frames available")
    blank = classify_screen(np.zeros((1080, 1920, 3), np.uint8), context=ctx)
    return {"frames": frames, "blank": blank}


def test_map_frames_never_read_as_panel_and_panel_signal_is_low(classified):
    for name, r in classified["frames"]:
        # SAFETY: a real map frame must never be reported as a province panel.
        assert r.state is not ScreenState.PROVINCE_PANEL, f"{name}: map read as panel!"
        assert r.candidates[ScreenState.PROVINCE_PANEL] < DEFAULT_MIN_CONFIDENCE


def test_positive_path_at_least_one_map_frame_is_gbg_map(classified):
    states = [r.state for _n, r in classified["frames"]]
    # the positive path works; badge-less frames may legitimately read UNKNOWN.
    assert any(s is ScreenState.GBG_MAP for s in states)
    assert all(s in (ScreenState.GBG_MAP, ScreenState.UNKNOWN) for s in states)


def test_blank_frame_is_unknown(classified):
    r = classified["blank"]
    assert r.state is ScreenState.UNKNOWN
    assert r.candidates[ScreenState.PROVINCE_PANEL] < DEFAULT_MIN_CONFIDENCE


def test_classification_is_observable(classified):
    _name, r = classified["frames"][0]
    d = r.to_dict()
    assert "confidence" in d and d["candidates"] and d["signals"]
    names = {s["name"] for s in d["signals"]}
    assert {"map_badges", "panel_emblem_score"} <= names
