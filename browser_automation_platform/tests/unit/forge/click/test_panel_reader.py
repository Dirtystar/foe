"""M6A.1 — the independent panel reader: fail-closed on uncertainty, an independent
colour signal, and classes are never collapsed (20≠40, 80≠100)."""

from __future__ import annotations

import numpy as np
import pytest

from bap.forge.click.panel_reader import COLOR_FAMILY, PanelReader, scaled_pill_center


class _FakeClassifier:
    def __init__(self, pct, sim, confirmed=True, n=10):
        self._pct, self._sim, self._confirmed, self._n = pct, sim, confirmed, n

    def __len__(self):
        return self._n

    def predict(self, patch):
        return (self._pct, self._sim)

    def confirmed(self, patch, **kw):
        return self._confirmed


def _frame(color_bgr):
    """A 1080x1920 BGR frame with a solid colour block around the panel pill."""
    img = np.full((1080, 1920, 3), 30, np.uint8)   # dark background
    cx, cy = scaled_pill_center(1920, 1080)
    img[cy - 40:cy + 40, cx - 40:cx + 40] = color_bgr
    return img


BLUE = (200, 60, 20)     # BGR ~ blue
RED = (20, 20, 200)      # BGR ~ red


def test_empty_bank_is_unknown_hard_stop():
    r = PanelReader(_FakeClassifier(40, 0.9, n=0))
    reading = r.read(_frame(BLUE))
    assert reading.ok is False and reading.pct is None
    assert "bank empty" in reading.reason.lower()


def test_confident_blue_40_reads_ok():
    r = PanelReader(_FakeClassifier(40, 0.9))
    reading = r.read(_frame(BLUE))
    assert reading.ok is True and reading.pct == 40
    assert reading.color_group == "blue"


def test_low_similarity_is_unknown():
    r = PanelReader(_FakeClassifier(20, 0.4))
    reading = r.read(_frame(BLUE))
    assert reading.ok is False and "UNKNOWN" in reading.reason


def test_unconfirmed_is_unknown():
    r = PanelReader(_FakeClassifier(20, 0.9, confirmed=False))
    reading = r.read(_frame(BLUE))
    assert reading.ok is False


def test_none_pct_is_unknown():
    r = PanelReader(_FakeClassifier(None, 0.2))
    reading = r.read(_frame(BLUE))
    assert reading.ok is False and reading.pct is None


def test_colour_percentage_contradiction_blocks():
    # Classifier claims 20% (blue family) but the pill is RED → gross family error.
    r = PanelReader(_FakeClassifier(20, 0.95))
    reading = r.read(_frame(RED))
    assert reading.ok is False
    assert "inconsistent" in reading.reason.lower()
    assert reading.color_group == "red"


def test_red_100_reads_ok_and_class_not_collapsed():
    r = PanelReader(_FakeClassifier(100, 0.9))
    reading = r.read(_frame(RED))
    assert reading.ok is True and reading.pct == 100     # 100 kept distinct from 80
    assert reading.color_group == "red"
    assert 100 in COLOR_FAMILY["red"] and 80 in COLOR_FAMILY["red"]


def test_colour_families_are_disjoint_on_the_safety_pair():
    # 20 and 40 share blue (colour can't split them); 80/100 share red.
    assert COLOR_FAMILY["blue"] == frozenset({20, 40})
    assert COLOR_FAMILY["red"] == frozenset({80, 100})
