import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.core.domain.models import Rect
from bap.forge.detection.calibration import WeakeningCalibration, resolution_key
from bap.forge.detection.weakening import (
    Decision,
    WeakeningRead,
    build_digit_templates,
    decide,
    read_ocr,
)
from bap.forge.detection.scan import build_scan
from bap.forge.worlds import World


def _digit_image(text, w=90, h=28):
    """Dark bar with light digits — stands in for a weakening number crop."""
    img = np.full((h, w, 3), 20, np.uint8)
    cv2.putText(img, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2, cv2.LINE_AA)
    return img


# --- calibration --------------------------------------------------------------


def test_resolution_key():
    assert resolution_key(1920, 1080) == "1920x1080"


def test_calibration_set_get_persist(tmp_path):
    path = tmp_path / "calibration.json"
    cal = WeakeningCalibration.load(path)
    assert cal.get(1920, 1080) is None
    cal.set(1920, 1080, Rect(700, 486, 60, 20))
    assert path.exists()  # set() autosaved

    reloaded = WeakeningCalibration.load(path)
    r = reloaded.get(1920, 1080)
    assert (r.x, r.y, r.w, r.h) == (700, 486, 60, 20)
    assert reloaded.get(1280, 720) is None  # different resolution


def test_calibration_rejects_zero_size(tmp_path):
    cal = WeakeningCalibration(tmp_path / "c.json")
    with pytest.raises(ValueError):
        cal.set(1920, 1080, Rect(1, 1, 0, 10))


# --- reader -------------------------------------------------------------------


def test_read_ocr_reads_a_number():
    img = _digit_image("42")
    read = read_ocr(img, Rect(0, 0, img.shape[1], img.shape[0]))
    assert read.value == 42
    assert read.confidence > 0.3
    assert read.method == "ocr"


def test_read_ocr_out_of_bounds():
    img = np.zeros((30, 90, 3), np.uint8)
    read = read_ocr(img, Rect(500, 500, 20, 20))
    assert read.value is None and read.confidence == 0.0


# --- fail-safe policy ---------------------------------------------------------


def test_decision_stop_at_or_over_limit():
    world = World(alias="H", hostname="cz8.forgeofempires.com", max_weakening=80)
    assert decide(WeakeningRead(80, 0.9, "ocr"), world) is Decision.STOP
    assert decide(WeakeningRead(120, 0.9, "ocr"), world) is Decision.STOP


def test_decision_continue_below_limit():
    world = World(alias="H", hostname="cz8.forgeofempires.com", max_weakening=80)
    assert decide(WeakeningRead(40, 0.9, "ocr"), world) is Decision.CONTINUE


def test_decision_unknown_when_unreadable_or_low_confidence():
    world = World(alias="H", hostname="cz8.forgeofempires.com", max_weakening=80)
    assert decide(WeakeningRead(None, 0.9, "ocr"), world) is Decision.UNKNOWN
    assert decide(WeakeningRead(10, 0.2, "ocr"), world) is Decision.UNKNOWN  # below conf floor


def test_never_continues_blindly_on_low_confidence():
    # Even a value that looks "safe" (below limit) must NOT continue if the read
    # is not confident.
    world = World(alias="H", hostname="cz8.forgeofempires.com", max_weakening=80)
    assert decide(WeakeningRead(5, 0.1, "ocr"), world) is Decision.UNKNOWN


# --- digit templates ----------------------------------------------------------


def test_build_digit_templates_from_labelled_samples():
    samples = [(_digit_image("10"), 10), (_digit_image("23"), 23)]
    templates = build_digit_templates(samples)
    # digits 0,1,2,3 should be learnable from "10" and "23"
    assert set(templates) >= {0, 1, 2, 3}


# --- scan integration + gate --------------------------------------------------


def test_scan_weakening_gate_stops_and_blocks_selection():
    # A frame whose weakening region reads over the limit => STOP, no selection.
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[486:514, 700:790] = _digit_image("99", w=90, h=28)
    world = World(alias="H", hostname="cz8.forgeofempires.com", max_weakening=80)
    scan = build_scan(frame, world=world, weakening_region=Rect(700, 486, 90, 28))
    assert scan.decision is Decision.STOP
    assert scan.selection.detection is None
    assert "STOP" in scan.explanation()
    assert scan.to_dict()["weakening"]["decision"] == "STOP"
