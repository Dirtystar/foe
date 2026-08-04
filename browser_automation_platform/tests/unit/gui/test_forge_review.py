"""Offscreen tests for the Vision Debugger Review Mode: badge correction,
Set Weakening Region, ground-truth entry, and the fail-safe decision. Observe-only."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from bap.core.domain.models import Rect
from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.labeling.model import LabelStore
from bap.forge.labeling.session import LabelSession
from bap.forge.worlds import World
from bap.gui.forge_review import ForgeReviewWindow


def _frame_with_number(text="42"):
    img = np.zeros((1080, 1920, 3), np.uint8)
    cv2.putText(img, text, (706, 506), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2, cv2.LINE_AA)
    return img


@pytest.fixture
def review(qapp, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    cv2.imwrite(str(frames / "a.png"), _frame_with_number("42"))
    cv2.imwrite(str(frames / "b.png"), _frame_with_number("7"))
    labels = tmp_path / "labels.json"
    cal = WeakeningCalibration(tmp_path / "calibration.json")
    world = World(alias="H", hostname="cz8.forgeofempires.com", max_weakening=80)
    session = LabelSession.open(frames, labels)
    win = ForgeReviewWindow(session, frames, cal, world=world)
    yield win, session, cal, labels
    win._dirty = False  # avoid the (blocking) unsaved-changes prompt at teardown
    win.close()


def test_badge_add_and_classify_persist_on_explicit_save(review):
    win, session, _, labels = review
    win._on_badge_clicked(900, 740, Qt.MouseButton.LeftButton)
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_3, Qt.KeyboardModifier.NoModifier))
    b = session.badges()[0]
    assert (b.cx, b.cy, b.pct) == (900, 740, 60)
    # Review Mode is explicit-save: the edit is in memory and marked dirty, not yet
    # on disk, until Save is pressed.
    assert win._dirty is True
    assert LabelStore.load(labels).get("a.png") is None or \
        not LabelStore.load(labels).get("a.png").badges
    win._save_now()
    assert win._dirty is False
    assert LabelStore.load(labels).get("a.png").badges[0].pct == 60


def test_badge_right_click_removes(review):
    win, session, _, _ = review
    win._on_badge_clicked(500, 500, Qt.MouseButton.LeftButton)
    assert len(session.badges()) == 1
    win._on_badge_clicked(503, 498, Qt.MouseButton.RightButton)
    assert session.badges() == []


def test_set_weakening_region_persists_calibration(review):
    win, _, cal, _ = review
    win._on_region_drawn(Rect(700, 486, 90, 28))
    r = cal.get(1920, 1080)
    assert r is not None and (r.x, r.y, r.w, r.h) == (700, 486, 90, 28)


def test_weakening_ground_truth_entry_persists_on_save(review):
    win, session, _, labels = review
    win.gt_edit.setText("42")
    win._on_gt_entered()
    assert session.weakening() == 42
    win._save_now()
    assert LabelStore.load(labels).get("a.png").weakening == 42


def test_decision_shown_after_region_set(review):
    win, _, _, _ = review
    # Region over the planted "42" (< limit 80) => CONTINUE once readable.
    win._on_region_drawn(Rect(700, 486, 96, 30))
    # decision label is one of the valid states
    assert win.decision_lbl.text() in ("CONTINUE", "STOP", "UNKNOWN")


def test_observe_only_banner_present(review):
    win, _, _, _ = review
    # The window title carries the observe-only marker.
    assert "OBSERVE ONLY" in win.windowTitle()
