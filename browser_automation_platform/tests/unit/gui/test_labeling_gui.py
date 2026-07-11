"""Offscreen smoke test for the labelling window: clicks add badges, number keys
classify, N marks a negative and advances, and everything autosaves."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from bap.forge.labeling.model import LabelStore
from bap.forge.labeling.session import LabelSession
from bap.forge.labeling.app import LabelWindow


@pytest.fixture
def frames_dir(tmp_path):
    for name in ("frame_a.png", "frame_b.png"):
        cv2.imwrite(str(tmp_path / name), np.zeros((1080, 1920, 3), np.uint8))
    return tmp_path


def _key(win, key):
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _window(frames_dir, qapp):
    labels = frames_dir / "labels.json"
    session = LabelSession.open(frames_dir, labels)
    return LabelWindow(session, frames_dir), session, labels


def test_click_adds_badge_and_key_classifies(qapp, frames_dir):
    win, session, labels = _window(frames_dir, qapp)

    win._on_canvas_clicked(900, 740, Qt.MouseButton.LeftButton)
    _key(win, Qt.Key.Key_3)  # 60%

    badges = session.badges()
    assert (badges[0].cx, badges[0].cy, badges[0].pct) == (900, 740, 60)
    # autosaved
    assert LabelStore.load(labels).get("frame_a.png").badges[0].pct == 60


def test_right_click_deletes(qapp, frames_dir):
    win, session, _ = _window(frames_dir, qapp)
    win._on_canvas_clicked(500, 500, Qt.MouseButton.LeftButton)
    assert len(session.badges()) == 1
    win._on_canvas_clicked(502, 498, Qt.MouseButton.RightButton)
    assert session.badges() == []


def test_negative_key_marks_reviewed_and_advances(qapp, frames_dir):
    win, session, labels = _window(frames_dir, qapp)
    assert session.current_file() == "frame_a.png"

    _key(win, Qt.Key.Key_N)

    saved = LabelStore.load(labels).get("frame_a.png")
    assert saved.reviewed is True and saved.badges == []
    assert session.current_file() == "frame_b.png"  # advanced


def test_advance_auto_marks_fully_classified(qapp, frames_dir):
    win, session, labels = _window(frames_dir, qapp)
    win._on_canvas_clicked(900, 740, Qt.MouseButton.LeftButton)
    _key(win, Qt.Key.Key_2)  # 40%
    _key(win, Qt.Key.Key_Right)  # advance

    assert LabelStore.load(labels).get("frame_a.png").reviewed is True
