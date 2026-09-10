"""Milestone — verify that opening a province produced the expected UI state.

Honest observation: report exactly the observed state (PROVINCE_PANEL / UNKNOWN /
GBG_MAP / …), never reinterpret it, never retry; and when it is not PROVINCE_PANEL,
save the screenshot + classifier output + context for later review.
"""

from __future__ import annotations

import json

import numpy as np

from bap.forge.state.province_open import (
    ProvinceOpenObservation,
    observe_province_open,
    save_confirmed_capture,
    save_unknown_capture,
)
from bap.forge.state.screen_state import (
    ScreenState,
    StateEvidence,
    StateSignal,
    classify_screen,
)


def _fake_detectors(map_score, panel_score):
    def _mk(state, score):
        def _det(image, ctx):
            return StateEvidence(score, [StateSignal(state, f"{state.value}_sig", score)])
        return _det
    return {ScreenState.GBG_MAP: _mk(ScreenState.GBG_MAP, map_score),
            ScreenState.PROVINCE_PANEL: _mk(ScreenState.PROVINCE_PANEL, panel_score)}


def _img():
    return np.zeros((80, 120, 3), np.uint8)


def test_observed_province_panel_is_confirmed_no_capture(tmp_path):
    obs = observe_province_open(
        _img(), detectors=_fake_detectors(0.1, 0.9), capture_dir=tmp_path)
    assert obs.observed is ScreenState.PROVINCE_PANEL
    assert obs.confirmed is True
    assert obs.captured_path is None                 # success → nothing saved
    assert list(tmp_path.iterdir()) == []


def test_confirmed_panel_is_captured_when_requested(tmp_path):
    # The success frame is the panel screenshot the dataset lacks — save it too.
    obs = observe_province_open(
        _img(), detectors=_fake_detectors(0.1, 0.9), capture_dir=tmp_path,
        capture_confirmed=True, exec_context={"world": "H"})
    assert obs.confirmed is True
    assert obs.captured_path is not None
    d = list(tmp_path.iterdir())[0]
    assert d.name.startswith("panel_")               # distinct from unknown_*
    assert (d / "screen.png").exists()
    ctx = json.loads((d / "context.json").read_text())
    assert ctx["observed_state"] == "PROVINCE_PANEL" and ctx["world"] == "H"


def test_confirmed_capture_off_by_default(tmp_path):
    obs = observe_province_open(
        _img(), detectors=_fake_detectors(0.1, 0.9), capture_dir=tmp_path)
    assert obs.confirmed is True and obs.captured_path is None
    assert list(tmp_path.iterdir()) == []


def test_save_confirmed_capture_is_best_effort(tmp_path):
    clf = classify_screen(_img(), detectors=_fake_detectors(0.1, 0.9))
    assert save_confirmed_capture("/nonexistent\0/bad", _img(), clf, {}) is None


def test_observed_unknown_is_reported_and_captured(tmp_path):
    # ambiguous scores → classifier returns UNKNOWN (no guessing)
    obs = observe_province_open(
        _img(), detectors=_fake_detectors(0.80, 0.78), capture_dir=tmp_path,
        exec_context={"world": "H", "resolution": [1920, 869]})
    assert obs.observed is ScreenState.UNKNOWN
    assert obs.confirmed is False
    assert obs.captured_path is not None
    # the bundle holds the screenshot + full classifier output + context
    d = list(tmp_path.iterdir())[0]
    assert (d / "screen.png").exists()
    cls = json.loads((d / "classification.json").read_text())
    assert "candidates" in cls and "signals" in cls
    ctx = json.loads((d / "context.json").read_text())
    assert ctx["world"] == "H" and ctx["observed_state"] == "UNKNOWN"


def test_observed_gbg_map_is_reported_honestly_not_reinterpreted(tmp_path):
    # The click did not open a panel; the screen is still the map. Report it as-is.
    obs = observe_province_open(
        _img(), detectors=_fake_detectors(0.95, 0.05), capture_dir=tmp_path)
    assert obs.observed is ScreenState.GBG_MAP     # NOT collapsed to UNKNOWN
    assert obs.confirmed is False
    assert obs.captured_path is not None           # anything != expected is captured


def test_none_image_is_unknown_and_captured(tmp_path):
    obs = observe_province_open(None, capture_dir=tmp_path)
    assert obs.observed is ScreenState.UNKNOWN and obs.confirmed is False
    # no screen.png (no image) but classification + context are still saved
    d = list(tmp_path.iterdir())[0]
    assert not (d / "screen.png").exists()
    assert (d / "classification.json").exists() and (d / "context.json").exists()


def test_capture_dir_none_never_writes():
    obs = observe_province_open(_img(), detectors=_fake_detectors(0.8, 0.78))
    assert obs.observed is ScreenState.UNKNOWN
    assert obs.captured_path is None               # no dir → nothing saved, no crash


def test_save_unknown_capture_is_best_effort(tmp_path):
    clf = classify_screen(_img(), detectors=_fake_detectors(0.8, 0.78))
    # a bad dir target must not raise
    path = save_unknown_capture("/nonexistent\0/bad", _img(), clf, {})
    assert path is None


def test_observation_to_dict_is_observable():
    obs = observe_province_open(_img(), detectors=_fake_detectors(0.1, 0.9))
    d = obs.to_dict()
    assert d["expected"] == "PROVINCE_PANEL" and d["observed"] == "PROVINCE_PANEL"
    assert d["confirmed"] is True and "classification" in d
    assert "confidence" in d
