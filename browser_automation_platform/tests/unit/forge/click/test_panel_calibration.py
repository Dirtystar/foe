"""M6A.1 — Panel Click Point Calibration: normalized coords, VERIFIED only when
stable across enough samples, drift reported, and the predicted point round-trips.
No action is ever performed by this tool."""

from __future__ import annotations

from bap.forge.click.panel_calibration import (
    MIN_SAMPLES_FOR_VERDICT,
    PanelClickCalibrationStore,
    PanelClickSample,
    analyze,
    predict_point,
)


def _sample(screen_point, panel_rect=(100, 100, 200, 100), world="H"):
    return PanelClickSample(
        screen_point=screen_point, panel_rect=panel_rect, viewport=(1900, 900),
        resolution=(1920, 1080), dpr=1.0, zoom=1.0,
        browser_mode="external_chrome", world=world)


def test_normalized_coords():
    s = _sample((150, 120))              # 50/200, 20/100
    assert s.normalized == (0.25, 0.2)


def test_predict_point_round_trips():
    assert predict_point((100, 100, 200, 100), (0.25, 0.2)) == (150, 120)
    # A different panel rect maps the same normalized point elsewhere.
    assert predict_point((300, 400, 400, 200), (0.25, 0.2)) == (400, 440)


def test_stable_samples_verify():
    # Same relative point across 3 different panel rectangles → VERIFIED.
    samples = [
        _sample((150, 120), (100, 100, 200, 100)),
        _sample((350, 240), (300, 200, 200, 100)),   # also (0.25, 0.4)? -> ensure same
    ]
    # make all exactly (0.25, 0.2)
    samples = [
        PanelClickSample((150, 120), (100, 100, 200, 100), (1900, 900), (1920, 1080), 1.0, 1.0, "x", "A"),
        PanelClickSample((350, 220), (300, 200, 200, 100), (1900, 900), (1920, 1080), 1.0, 1.0, "x", "B"),
        PanelClickSample((550, 320), (500, 300, 200, 100), (1900, 900), (1920, 1080), 1.0, 1.0, "x", "C"),
    ]
    v = analyze(samples)
    assert v.verified is True and v.samples == 3
    assert abs(v.mean_normalized[0] - 0.25) < 1e-9 and abs(v.mean_normalized[1] - 0.2) < 1e-9


def test_too_few_samples_not_verified():
    v = analyze([_sample((150, 120))])
    assert v.verified is False
    assert str(MIN_SAMPLES_FOR_VERDICT) in v.reason


def test_drift_not_verified():
    samples = [
        PanelClickSample((150, 120), (100, 100, 200, 100), (1900, 900), (1920, 1080), 1.0, 1.0, "x", "A"),
        PanelClickSample((390, 280), (300, 200, 200, 100), (1900, 900), (1920, 1080), 1.0, 1.0, "x", "B"),  # (0.45,0.8)
        PanelClickSample((520, 360), (500, 300, 200, 100), (1900, 900), (1920, 1080), 1.0, 1.0, "x", "C"),  # (0.1,0.6)
    ]
    v = analyze(samples)
    assert v.verified is False and "drift" in v.reason.lower()


def test_store_persists_and_reloads(tmp_path):
    p = tmp_path / "cal.json"
    store = PanelClickCalibrationStore(p)
    store.add(_sample((150, 120)))
    store.add(_sample((151, 121)))
    reloaded = PanelClickCalibrationStore(p)
    assert len(reloaded.samples) == 2
    assert reloaded.samples[0].screen_point == (150, 120)


def test_draw_prediction_marks_point_without_error():
    import numpy as np

    from bap.forge.click.panel_calibration import draw_prediction, predict_point

    img = np.zeros((200, 300, 3), np.uint8)
    out = draw_prediction(img, (50, 40, 100, 80), (0.5, 0.5), verified=True)
    assert out.shape == img.shape
    # something was drawn (not an all-black copy)
    assert int(out.sum()) > 0
    assert predict_point((50, 40, 100, 80), (0.5, 0.5)) == (100, 80)
