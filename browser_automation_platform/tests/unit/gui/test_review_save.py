"""Reliable Review-Mode save workflow (Milestone 4.14).

Reproduces and pins the fix for the Windows bug where Review edits (and especially
``reviewed=true``) did not persist: Review Mode is now explicit-save, with a Save
button, a Reviewed control, dirty tracking, and a close confirmation. Uses real
LabelStore serialization in temp dirs.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent

from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.labeling.model import LabelStore
from bap.forge.labeling.session import LabelSession
from bap.gui.forge_review import ForgeReviewWindow


def _dataset(tmp_path, frames=("a.png", "neg.png")):
    fdir = tmp_path / "frames"
    fdir.mkdir()
    for name in frames:
        cv2.imwrite(str(fdir / name), np.full((200, 300, 3), 40, np.uint8))
    return fdir, tmp_path / "labels.json"


def _win(qapp, fdir, labels):
    session = LabelSession.open(fdir, labels)
    return ForgeReviewWindow(session, fdir, WeakeningCalibration()), session


def test_explicit_save_writes_to_requested_labels_path(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    try:
        assert s.store.autosave is False               # explicit-save mode
        s.goto(0); s.add_badge(120, 90); win._mark_dirty()
        assert not labels.exists() or not LabelStore.load(labels).get("a.png").badges
        win._save_now()
        # Written to the exact path passed on launch.
        assert LabelStore.load(labels).get("a.png").badges, "save must write to the launch labels path"
        # No duplicate labels.json created inside frames/.
        assert not (fdir / "labels.json").exists()
    finally:
        win._dirty = False; win.close()


def test_save_persists_addition_deletion_and_pct(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    try:
        s.goto(0)
        win._on_badge_clicked(100, 80, Qt.MouseButton.LeftButton)   # add
        win._on_badge_clicked(200, 150, Qt.MouseButton.LeftButton)  # add second
        win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier))  # 20%
        win._save_now()
        stored = LabelStore.load(labels).get("a.png")
        assert len(stored.badges) == 2
        assert any(b.pct == 20 for b in stored.badges)
        # Delete one and save -> deletion persists.
        win._on_badge_clicked(200, 150, Qt.MouseButton.RightButton)
        win._save_now()
        assert len(LabelStore.load(labels).get("a.png").badges) == 1
    finally:
        win._dirty = False; win.close()


def test_save_persists_reviewed_true(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    try:
        s.goto(0); win._on_badge_clicked(120, 90, Qt.MouseButton.LeftButton)
        win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier))
        win.reviewed_check.setChecked(True)            # explicit Mark Reviewed
        assert win._dirty is True
        win._save_now()
        stored = LabelStore.load(labels).get("a.png")
        assert stored.reviewed is True
        assert stored.badges and stored.badges[0].pct == 20   # labels preserved
    finally:
        win._dirty = False; win.close()


def test_reviewed_negative_with_zero_badges_persists(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    try:
        s.goto(1)                                       # neg.png, no badges
        win._load()
        win.reviewed_check.setChecked(True)             # the bug: this was impossible before
        win._save_now()
        stored = LabelStore.load(labels).get("neg.png")
        assert stored.reviewed is True and stored.badges == []
    finally:
        win._dirty = False; win.close()


def test_reopen_restores_saved_state(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    s.goto(0); win._on_badge_clicked(120, 90, Qt.MouseButton.LeftButton)
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier))  # 40
    win.reviewed_check.setChecked(True)
    win._save_now(); win._dirty = False; win.close()

    win2, s2 = _win(qapp, fdir, labels)
    try:
        a = s2.store.get("a.png")
        assert a.reviewed is True and a.badges[0].pct == 40
        # The session resumes at the first UNREVIEWED frame ("neg.png"); navigate
        # BACK to the reviewed "a.png" (which sorts first) to confirm the UI
        # restores its reviewed state on load. Use prev(): next() clamps at the
        # last index, so a forward walk from the resume point can never reach an
        # earlier frame and would spin forever.
        while s2.current_file() != "a.png":
            s2.prev()
        win2._load()
        assert win2.reviewed_check.isChecked() is True  # UI restores reviewed state
    finally:
        win2._dirty = False; win2.close()


def test_close_with_unsaved_prompts_and_discard_does_not_write(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    s.goto(0); win._on_badge_clicked(120, 90, Qt.MouseButton.LeftButton)
    assert win._dirty is True
    prompted = {"n": 0}

    def fake_prompt():
        prompted["n"] += 1
        return "discard"

    win._prompt_unsaved = fake_prompt
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert prompted["n"] == 1, "closing with unsaved changes must prompt"
    # Discard did not write.
    assert not labels.exists() or LabelStore.load(labels).get("a.png") is None or \
        not LabelStore.load(labels).get("a.png").badges


def test_close_cancel_keeps_window_open(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    try:
        s.goto(0); win._on_badge_clicked(120, 90, Qt.MouseButton.LeftButton)
        win._prompt_unsaved = lambda: "cancel"
        ev = QCloseEvent()
        win.closeEvent(ev)
        assert ev.isAccepted() is False, "Cancel must keep the window open"
        assert win._dirty is True
    finally:
        win._dirty = False; win.close()


def test_close_save_writes(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    s.goto(0); win._on_badge_clicked(120, 90, Qt.MouseButton.LeftButton)
    win._prompt_unsaved = lambda: "save"
    win.closeEvent(QCloseEvent())
    assert LabelStore.load(labels).get("a.png").badges, "Save-on-close must write"


def test_duplicate_labels_in_frames_is_warned(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    (fdir / "labels.json").write_text('{"version":1,"frames":[]}', encoding="utf-8")
    win, s = _win(qapp, fdir, labels)
    try:
        win._load()
        assert "different labels.json" in win.dup_warn_lbl.text()
    finally:
        win._dirty = False; win.close()


def test_labels_path_is_visible(qapp, tmp_path):
    fdir, labels = _dataset(tmp_path)
    win, s = _win(qapp, fdir, labels)
    try:
        win._load()
        assert str(labels) in win.labels_path_lbl.text()
    finally:
        win._dirty = False; win.close()
