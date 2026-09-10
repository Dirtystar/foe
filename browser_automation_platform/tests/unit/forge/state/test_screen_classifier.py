"""Milestone A — UI state classifier: the fail-safe decision rule and the registry
composition, tested purely with fake detectors (no vision, deterministic)."""

from __future__ import annotations

import numpy as np

from bap.forge.state.screen_state import (
    DEFAULT_MIN_CONFIDENCE,
    ScreenClassification,
    ScreenState,
    StateEvidence,
    StateSignal,
    classify_screen,
    decide,
)


# --- the pure decision rule ---------------------------------------------------

def test_clear_winner_is_chosen():
    state, conf, _ = decide({ScreenState.GBG_MAP: 0.85, ScreenState.PROVINCE_PANEL: 0.1})
    assert state is ScreenState.GBG_MAP and conf == 0.85


def test_below_confidence_is_unknown():
    state, _, reason = decide({ScreenState.GBG_MAP: 0.5, ScreenState.PROVINCE_PANEL: 0.1})
    assert state is ScreenState.UNKNOWN and "0.50" in reason


def test_small_margin_is_unknown():
    # Both high but too close to tell apart → UNKNOWN (no guessing).
    state, _, reason = decide({ScreenState.GBG_MAP: 0.80, ScreenState.PROVINCE_PANEL: 0.75})
    assert state is ScreenState.UNKNOWN and "margin" in reason.lower()


def test_no_scores_is_unknown():
    state, _, _ = decide({})
    assert state is ScreenState.UNKNOWN


# --- classify_screen composition with fake detectors --------------------------

def _fake(score, name="sig"):
    def _det(image, ctx):
        return StateEvidence(score, [StateSignal(ScreenState.GBG_MAP, name, score)])
    return _det


def _img():
    return np.zeros((100, 100, 3), np.uint8)


def test_map_detector_wins():
    dets = {ScreenState.GBG_MAP: _fake(0.82), ScreenState.PROVINCE_PANEL: _fake(0.1)}
    r = classify_screen(_img(), detectors=dets, context=None)
    assert r.state is ScreenState.GBG_MAP and r.confidence == 0.82
    assert r.candidates[ScreenState.GBG_MAP] == 0.82


def test_panel_detector_wins():
    dets = {ScreenState.GBG_MAP: _fake(0.2), ScreenState.PROVINCE_PANEL: _fake(0.88)}
    r = classify_screen(_img(), detectors=dets, context=None)
    assert r.state is ScreenState.PROVINCE_PANEL


def test_ambiguous_falls_back_to_unknown():
    dets = {ScreenState.GBG_MAP: _fake(0.80), ScreenState.PROVINCE_PANEL: _fake(0.78)}
    r = classify_screen(_img(), detectors=dets, context=None)
    assert r.state is ScreenState.UNKNOWN


def test_all_low_is_unknown():
    dets = {ScreenState.GBG_MAP: _fake(0.2), ScreenState.PROVINCE_PANEL: _fake(0.1)}
    r = classify_screen(_img(), detectors=dets, context=None)
    assert r.state is ScreenState.UNKNOWN


def test_none_image_is_unknown_without_running_detectors():
    calls = []

    def _boom(image, ctx):
        calls.append(1)
        raise AssertionError("should not run on None image")

    r = classify_screen(None, detectors={ScreenState.GBG_MAP: _boom})
    assert r.state is ScreenState.UNKNOWN and calls == []


def test_broken_detector_abstains_never_wins():
    def _boom(image, ctx):
        raise RuntimeError("detector crashed")

    dets = {ScreenState.GBG_MAP: _boom, ScreenState.PROVINCE_PANEL: _fake(0.9)}
    r = classify_screen(_img(), detectors=dets, context=None)
    # crashed map detector contributes 0; panel wins; nothing guessed
    assert r.candidates[ScreenState.GBG_MAP] == 0.0
    assert r.state is ScreenState.PROVINCE_PANEL


def test_registry_is_extensible_new_state_scored():
    # A future state added by simply registering a detector shows up in candidates.
    class _S(str):
        pass

    extra = ScreenState.PROVINCE_PANEL  # reuse an enum member as a stand-in
    dets = {ScreenState.GBG_MAP: _fake(0.3), extra: _fake(0.4)}
    r = classify_screen(_img(), detectors=dets, context=None)
    assert set(r.candidates) == {ScreenState.GBG_MAP, extra}


def test_structured_log_shape():
    dets = {ScreenState.GBG_MAP: _fake(0.82), ScreenState.PROVINCE_PANEL: _fake(0.1)}
    r = classify_screen(_img(), detectors=dets, context=None)
    d = r.to_dict()
    assert set(d) == {"state", "confidence", "reason", "candidates", "signals"}
    assert d["state"] == "GBG_MAP"
    assert d["candidates"]["GBG_MAP"] == 0.82
    assert isinstance(d["signals"], list) and d["signals"][0]["name"] == "sig"


def test_map_detector_reuses_precomputed_detections_without_scanning():
    # The reuse hook: given a caller's existing detections, no scan is performed.
    from bap.forge.state.detectors import DetectContext, detect_gbg_map

    class _BoomDetector:
        def scan(self, *a, **k):
            raise AssertionError("must not scan when detections are provided")

    ctx = DetectContext(detector=_BoomDetector(), map_detections=[object(), object(), object()])
    ev = detect_gbg_map(_img(), ctx)
    assert ev.score > DEFAULT_MIN_CONFIDENCE          # 3 badges → confident map
    assert ev.signals[0].value == 3


def test_confidence_default_is_conservative():
    # A single mediocre signal must not be enough to claim a state.
    assert DEFAULT_MIN_CONFIDENCE >= 0.6
    dets = {ScreenState.GBG_MAP: _fake(DEFAULT_MIN_CONFIDENCE - 0.01)}
    r = classify_screen(_img(), detectors=dets, context=None)
    assert r.state is ScreenState.UNKNOWN
